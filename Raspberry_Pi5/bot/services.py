"""Background services for the bot."""
import asyncio
import logging
from telegram import Bot
from utils.network_scanner import scan_network
from presence.device_manager import DeviceManager

logger = logging.getLogger(__name__)

async def telegram_ping_worker(bot: Bot, device_manager: DeviceManager, telegram_ping_queue: asyncio.Queue):
    """Process device ping requests via Telegram notifications."""
    logger.info("Starting Telegram ping worker")
    
    while True:
        try:
            task_data = await asyncio.get_event_loop().run_in_executor(None, telegram_ping_queue.get)
            
            mac = task_data['mac']
            telegram_user_id = task_data['telegram_user_id']
            ip_address = task_data.get('ip_address')
            
            logger.info(f"Processing Telegram ping for device {mac} (user {telegram_user_id}, IP: {ip_address})")
            
            try:
                sent_message = await bot.send_message(
                    chat_id=telegram_user_id, 
                    text=".",
                    disable_notification=True
                )
                logger.info(f"Sent Telegram ping to user {telegram_user_id} for device {mac}")
                
                await asyncio.sleep(0.5)
                try:
                    await bot.delete_message(
                        chat_id=sent_message.chat_id, 
                        message_id=sent_message.message_id
                    )
                    logger.debug(f"Deleted ping message {sent_message.message_id} for user {telegram_user_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete ping message: {e}")
                
            except Exception as e:
                logger.error(f"Failed to send Telegram ping to user {telegram_user_id}: {e}")
                if device_manager:
                    device_manager.process_telegram_ping_result(mac, False)
                telegram_ping_queue.task_done()
                continue
            
            await asyncio.sleep(15) 
            
            try:
                detected_after_ping = False
                loop = asyncio.get_event_loop()
                
                scan_results = await loop.run_in_executor(None, scan_network, ip_address)
                
                for device_mac, device_ip_found, _ in scan_results:
                    if device_mac.lower() == mac.lower():
                        detected_after_ping = True
                        logger.info(f"Device {mac} detected on network after Telegram ping (IP: {device_ip_found})")
                        break
                
                logger.debug(f"Post-ping scan result for {mac}: detected={detected_after_ping}")
                if device_manager:
                    device_manager.process_telegram_ping_result(mac, detected_after_ping)
                
            except Exception as e:
                logger.error(f"Error during post-ping scan for {mac}: {e}")
                if device_manager:
                    device_manager.process_telegram_ping_result(mac, False)
            
            telegram_ping_queue.task_done()
            
        except asyncio.CancelledError:
            logger.info("Telegram ping worker cancelled")
            break
        except Exception as e:
            logger.error(f"Unhandled error in Telegram ping worker loop: {e}", exc_info=True)
            await asyncio.sleep(1) 
    
    logger.info("Telegram ping worker stopped")