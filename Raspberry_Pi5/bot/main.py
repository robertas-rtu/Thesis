# bot/main.py
"""Telegram bot main entry point."""
import os
import sys
import logging
import asyncio
from telegram.ext import Application, CallbackQueryHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import BOT_TOKEN, ADMIN_ID, DATA_DIR, OCCUPANCY_HISTORY_FILE
from bot.handlers.commands import setup_command_handlers
from bot.handlers.messages import setup_message_handlers
from bot.user_auth import UserAuth
from bot.handlers.ventilation import setup_ventilation_handlers, handle_vent_callback
from bot.handlers.sleep_patterns import setup_sleep_handlers
from predictive.occupancy_pattern_analyzer import OccupancyPatternAnalyzer
from bot.services import telegram_ping_worker

logger = logging.getLogger(__name__)
bot_file_handler = logging.FileHandler("bot.log")
bot_file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
bot_file_handler.setFormatter(bot_file_formatter)
bot_file_handler.setLevel(logging.INFO)
logger.addHandler(bot_file_handler)

_stop_bot = False

async def heartbeat_task():
    """Bot heartbeat task."""
    while not _stop_bot:
        logger.info("Bot is running - heartbeat")
        await asyncio.sleep(30)

async def async_main(pico_manager=None, controller=None, data_manager=None, sleep_analyzer=None, preference_manager=None, occupancy_analyzer=None, device_manager=None, telegram_ping_tasks_queue=None):
    """Initialize and run bot."""
    global _stop_bot
    
    user_auth = UserAuth(DATA_DIR)
    application = Application.builder().token(BOT_TOKEN).build()
    
    if not preference_manager:
        from preferences.preference_manager import PreferenceManager
        preference_manager = PreferenceManager()
    
    if not occupancy_analyzer:
        occupancy_analyzer = OccupancyPatternAnalyzer(OCCUPANCY_HISTORY_FILE)

    application.bot_data["user_auth"] = user_auth
    application.bot_data["pico_manager"] = pico_manager
    application.bot_data["controller"] = controller
    application.bot_data["data_manager"] = data_manager
    application.bot_data["sleep_analyzer"] = sleep_analyzer
    application.bot_data["preference_manager"] = preference_manager
    application.bot_data["occupancy_analyzer"] = occupancy_analyzer
    application.bot_data["device_manager"] = device_manager
    
    setup_command_handlers(application)
    setup_message_handlers(application)
    setup_ventilation_handlers(application)
    setup_sleep_handlers(application)
    from bot.handlers.preferences import setup_preference_handlers
    setup_preference_handlers(application)
    from bot.handlers.occupancy import setup_occupancy_handlers
    setup_occupancy_handlers(application)
    
    heartbeat = asyncio.create_task(heartbeat_task())
    logger.info("Bot heartbeat task created")
    
    logger.info("Bot starting polling...")
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot polling started")
        
        if telegram_ping_tasks_queue is not None and device_manager is not None:
            ping_task = asyncio.create_task(telegram_ping_worker(application.bot, device_manager, telegram_ping_tasks_queue))
            logger.info("Started Telegram ping worker")
        
        while not _stop_bot:
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Error in bot main loop: {e}", exc_info=True)
    finally:
        logger.info("Stopping bot...")
        await application.stop() 
        await application.shutdown() 
        
        if 'heartbeat' in locals() and heartbeat and not heartbeat.done():
            heartbeat.cancel()
        logger.info("Bot stopped")

def main(pico_manager=None, controller=None, data_manager=None, sleep_analyzer=None, preference_manager=None, occupancy_analyzer=None, device_manager=None, telegram_ping_tasks_queue=None):
    """Main bot entry point."""
    global _stop_bot
    
    try:
        logger.info("Starting telegram bot")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        loop.run_until_complete(async_main(pico_manager, controller, data_manager, sleep_analyzer, preference_manager, occupancy_analyzer, device_manager, telegram_ping_tasks_queue))
        
    except Exception as e:
        logger.critical(f"Error starting bot: {e}", exc_info=True)
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt")
    finally:
        _stop_bot = True
        
        if 'loop' in locals():
            try:
                all_tasks_in_loop = asyncio.all_tasks(loop)
                if all_tasks_in_loop:
                    for task in all_tasks_in_loop:
                        if not task.done():
                            task.cancel()
                
                if not loop.is_closed():
                    loop.close()
                    logger.info("Event loop closed.")
                else:
                    logger.info("Event loop was already closed before explicit close call in finally.")

            except RuntimeError as e:
                logger.error(f"RuntimeError during event loop cleanup: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error during event loop cleanup: {e}", exc_info=True)
        else:
            logger.warning("Event loop variable 'loop' not found in main's finally block for cleanup.")

if __name__ == "__main__":
    main()