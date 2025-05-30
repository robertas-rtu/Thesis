# control/ventilation_controller.py
"""Simple threshold-based ventilation controller."""
import logging
import threading
import time
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class VentilationController:
    
    def __init__(self, data_manager, pico_manager, scan_interval=60):
        self.data_manager = data_manager
        self.pico_manager = pico_manager
        self.scan_interval = scan_interval
        
        self.running = False
        self.thread = None
        
        self.co2_thresholds = {
            "low": 800,
            "medium": 1000,
            "high": 1200
        }
        
        self.temp_thresholds = {
            "low": 18,
            "medium": 20,
            "high": 25
        }
        
        self.auto_mode = True
        self.last_action_time = None
        self.min_ventilation_time = 300  # Minimum ventilation runtime in seconds
        self.min_off_time = 600  # Minimum time between ventilation cycles in seconds
        
        self.night_mode_enabled = True
        self.night_mode_start_hour = 23
        self.night_mode_end_hour = 7
        
        self.settings_dir = "data/ventilation"
        os.makedirs(self.settings_dir, exist_ok=True)
        
        self._load_night_mode_settings()
    
    def _load_night_mode_settings(self):
        night_settings_file = os.path.join(self.settings_dir, "night_mode_settings.json")
        try:
            if os.path.exists(night_settings_file):
                with open(night_settings_file, 'r') as f:
                    settings = json.load(f)
                    self.night_mode_enabled = settings.get("enabled", True)
                    self.night_mode_start_hour = settings.get("start_hour", 23)
                    self.night_mode_end_hour = settings.get("end_hour", 7)
                    logger.info(f"Loaded night mode settings: {self.night_mode_start_hour}:00 - {self.night_mode_end_hour}:00")
        except Exception as e:
            logger.error(f"Error loading night mode settings: {e}")
    
    def _save_night_mode_settings(self):
        night_settings_file = os.path.join(self.settings_dir, "night_mode_settings.json")
        try:
            settings = {
                "enabled": self.night_mode_enabled,
                "start_hour": self.night_mode_start_hour,
                "end_hour": self.night_mode_end_hour
            }
            with open(night_settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
            logger.info("Saved night mode settings")
        except Exception as e:
            logger.error(f"Error saving night mode settings: {e}")
    
    def _is_night_mode_active(self):
        if not self.night_mode_enabled:
            return False
        
        current_hour = datetime.now().hour
        
        if self.night_mode_start_hour > self.night_mode_end_hour:
            # Night mode spans midnight (e.g., 23:00 - 7:00)
            return current_hour >= self.night_mode_start_hour or current_hour < self.night_mode_end_hour
        else:
            # Night mode within same day
            return self.night_mode_start_hour <= current_hour < self.night_mode_end_hour
    
    def start(self):
        if self.thread is not None and self.thread.is_alive():
            logger.warning("Ventilation controller already running")
            return False
        
        self.running = True
        self.thread = threading.Thread(target=self._control_loop, daemon=True)
        self.thread.start()
        logger.info("Started ventilation controller")
        return True
    
    def stop(self):
        self.running = False
        logger.info("Stopped ventilation controller")
    
    def _control_loop(self):
        while self.running:
            try:
                if not self.auto_mode:
                    time.sleep(self.scan_interval)
                    continue
                
                if self._is_night_mode_active():
                    current_status = self.pico_manager.get_ventilation_status()
                    if current_status:
                        logger.info("Night mode active - turning off ventilation")
                        self._turn_ventilation_off("Night mode active")
                    time.sleep(self.scan_interval)
                    continue
                
                sensor_data = self._get_current_data()
                action, speed, reason = self._determine_action(sensor_data)
                
                if action == "on":
                    self._turn_ventilation_on(speed, reason)
                elif action == "off":
                    self._turn_ventilation_off(reason)
                
                time.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"Error in ventilation control loop: {e}")
                time.sleep(self.scan_interval)
    
    def _get_current_data(self):
        data = {}
        
        # Environmental readings
        data["co2"] = self.data_manager.latest_data["scd41"]["co2"]
        data["temperature"] = self.data_manager.latest_data["scd41"]["temperature"]
        data["humidity"] = self.data_manager.latest_data["scd41"]["humidity"]
        
        # Room state
        data["occupants"] = self.data_manager.latest_data["room"]["occupants"]
        data["ventilated"] = self.data_manager.latest_data["room"]["ventilated"]
        data["ventilation_speed"] = self.data_manager.latest_data["room"]["ventilation_speed"]
        
        # Timing info
        if self.last_action_time:
            data["time_since_last_action"] = (datetime.now() - self.last_action_time).total_seconds()
        else:
            data["time_since_last_action"] = float('inf')
        
        return data
    
    def _determine_action(self, data):
        action = "maintain"
        speed = data["ventilation_speed"]
        reason = "No change needed"
        
        if data["co2"] is None:
            return action, speed, "Missing CO2 data"
        
        # Check timing constraints
        if data["ventilated"] and data["time_since_last_action"] < self.min_ventilation_time:
            return "maintain", speed, f"Minimum ventilation time not reached ({data['time_since_last_action']:.0f}s < {self.min_ventilation_time}s)"
        
        if not data["ventilated"] and data["time_since_last_action"] < self.min_off_time:
            return "maintain", speed, f"Minimum off time not reached ({data['time_since_last_action']:.0f}s < {self.min_off_time}s)"
        
        # Adjust thresholds when unoccupied
        co2_threshold_adjustment = 0
        if data["occupants"] == 0:
            co2_threshold_adjustment = 200
        
        co2 = data["co2"]
        
        # Decision tree based on CO2 levels
        if co2 > self.co2_thresholds["high"] + co2_threshold_adjustment:
            return "on", "max", f"High CO2 level: {co2} ppm > {self.co2_thresholds['high'] + co2_threshold_adjustment} ppm"
        
        elif co2 > self.co2_thresholds["medium"] + co2_threshold_adjustment:
            return "on", "medium", f"Elevated CO2 level: {co2} ppm > {self.co2_thresholds['medium'] + co2_threshold_adjustment} ppm"
        
        elif co2 > self.co2_thresholds["low"] + co2_threshold_adjustment:
            return "on", "low", f"Slightly elevated CO2 level: {co2} ppm > {self.co2_thresholds['low'] + co2_threshold_adjustment} ppm"
        
        else:
            return "off", None, f"Low CO2 level: {co2} ppm < {self.co2_thresholds['low'] + co2_threshold_adjustment} ppm"
    
    def _turn_ventilation_on(self, speed, reason):
        current_status = self.pico_manager.get_ventilation_status()
        current_speed = self.pico_manager.get_ventilation_speed()
        
        if current_status and current_speed == speed:
            return
        
        success = self.pico_manager.control_ventilation("on", speed)
        
        if success:
            self.last_action_time = datetime.now()
            logger.info(f"Turned ventilation ON at {speed} speed. Reason: {reason}")
        else:
            logger.error(f"Failed to turn ventilation on at {speed} speed")
    
    def _turn_ventilation_off(self, reason):
        current_status = self.pico_manager.get_ventilation_status()
        
        if not current_status:
            return
        
        success = self.pico_manager.control_ventilation("off")
        
        if success:
            self.last_action_time = datetime.now()
            logger.info(f"Turned ventilation OFF. Reason: {reason}")
        else:
            logger.error("Failed to turn ventilation off")
    
    def set_auto_mode(self, enabled):
        self.auto_mode = enabled
        logger.info(f"Automatic control {'enabled' if enabled else 'disabled'}")
        return True
    
    def set_night_mode(self, enabled, start_hour=None, end_hour=None):
        self.night_mode_enabled = enabled
        if start_hour is not None:
            self.night_mode_start_hour = start_hour
        if end_hour is not None:
            self.night_mode_end_hour = end_hour
        
        self._save_night_mode_settings()
        logger.info(f"Night mode {'enabled' if enabled else 'disabled'}: {self.night_mode_start_hour}:00 - {self.night_mode_end_hour}:00")
        return True
    
    def get_status(self):
        return {
            "auto_mode": self.auto_mode,
            "co2_thresholds": self.co2_thresholds,
            "temp_thresholds": self.temp_thresholds,
            "ventilation_status": self.pico_manager.get_ventilation_status(),
            "ventilation_speed": self.pico_manager.get_ventilation_speed(),
            "last_action_time": self.last_action_time.isoformat() if self.last_action_time else None,
            "night_mode": {
                "enabled": self.night_mode_enabled,
                "start_hour": self.night_mode_start_hour,
                "end_hour": self.night_mode_end_hour,
                "currently_active": self._is_night_mode_active()
            }
        }
    
    def set_thresholds(self, co2_low=None, co2_medium=None, co2_high=None):
        if co2_low is not None:
            self.co2_thresholds["low"] = co2_low
        if co2_medium is not None:
            self.co2_thresholds["medium"] = co2_medium
        if co2_high is not None:
            self.co2_thresholds["high"] = co2_high
        
        logger.info(f"Updated CO2 thresholds: {self.co2_thresholds}")
        return True