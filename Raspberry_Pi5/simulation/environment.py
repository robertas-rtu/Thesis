# simulation/environment.py
"""Environment simulator for the ventilation system."""
import numpy as np
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class EnvironmentSimulator:
    
    def __init__(self, 
                 initial_co2=420,
                 initial_temp=20.0,
                 initial_humidity=40.0,
                 room_volume=62.5,
                 co2_natural_decay=128.8,
                 temp_natural_decay=0.5,
                 outdoor_co2=420,
                 outdoor_temp_min=15.0,
                 outdoor_temp_max=25.0,
                 outdoor_humidity=40.0,
                 co2_per_person=243.1):
        self.co2 = initial_co2
        self.temperature = initial_temp
        self.humidity = initial_humidity
        
        self.room_volume = room_volume
        self.co2_natural_decay = co2_natural_decay
        self.temp_natural_decay = temp_natural_decay
        
        self.outdoor_co2 = outdoor_co2
        self.outdoor_temp_min = outdoor_temp_min
        self.outdoor_temp_max = outdoor_temp_max
        self.outdoor_humidity = outdoor_humidity
        
        self.co2_per_person = co2_per_person
        
        self.ventilation_rates = {
            "natural": 610.3,
            "mechanical_low": 305.4,
            "mechanical_medium": 670.7,
            "mechanical_max": 824.3
        }
        
        self.temp_ventilation_effects = {
            "natural": 3.0,
            "mechanical_low": 1.0,
            "mechanical_medium": 1.5,
            "mechanical_max": 2.0
        }
        
        self.humidity_ventilation_effects = {
            "natural": 10.0,
            "mechanical_low": 3.0,
            "mechanical_medium": 6.0,
            "mechanical_max": 8.0
        }
        
        self.current_time = datetime(2023, 1, 2, 0, 0, 0)
        self.history = []
        
        self._record_state()
    
    def _get_outdoor_temperature(self):
        hour = self.current_time.hour
        minute = self.current_time.minute
        
        day_of_year = self.current_time.timetuple().tm_yday
        yearly_factor = np.sin(2 * np.pi * (day_of_year - 172) / 365)
        
        daily_factor = np.sin(2 * np.pi * ((hour + minute/60) - 3) / 24)
        
        temp_range = (self.outdoor_temp_max - self.outdoor_temp_min) / 2
        temp_avg = (self.outdoor_temp_max + self.outdoor_temp_min) / 2
        
        outdoor_temp = temp_avg + temp_range * (0.8 * yearly_factor + 0.2 * daily_factor)
        
        return max(self.outdoor_temp_min, min(self.outdoor_temp_max, outdoor_temp))
    
    def _calculate_night_co2_change(self, time_step_hours, occupants):
        night_decay_rate = 159.0
        sleeping_co2_per_person = 40.0
        
        current_co2 = self.co2
        
        current_hour = self.current_time.hour
        
        if 3 <= current_hour < 6:
            target_co2 = 780 + (occupants * 15)
            
            if current_co2 > target_co2 + 50:
                co2_change = (target_co2 - current_co2) * 0.3 * time_step_hours
            elif current_co2 < target_co2 - 20:
                co2_change = (target_co2 - current_co2) * 0.2 * time_step_hours
            else:
                co2_change = (target_co2 - current_co2) * 0.1 * time_step_hours
        
        else:
            co2_decay = night_decay_rate * time_step_hours
            co2_production = occupants * sleeping_co2_per_person * time_step_hours
            co2_change = co2_production - co2_decay
        
        return co2_change

    def update(self, time_step_minutes, occupants, ventilation_mode=None, ventilation_speed=None):
        time_step_hours = time_step_minutes / 60.0
        
        self.current_time += timedelta(minutes=time_step_minutes)
        
        outdoor_temp = self._get_outdoor_temperature()
        
        is_night = (22 <= self.current_time.hour or self.current_time.hour < 7)
        
        if is_night:
            co2_night_change = self._calculate_night_co2_change(time_step_hours, occupants)
            
            co2_ventilation = 0
            if ventilation_mode == 'natural':
                co2_ventilation = self.ventilation_rates["natural"] * time_step_hours
            elif ventilation_mode == 'mechanical' and ventilation_speed in ['low', 'medium', 'max']:
                vent_key = f"mechanical_{ventilation_speed}"
                co2_ventilation = self.ventilation_rates[vent_key] * time_step_hours
            
            co2_net_change = co2_night_change - co2_ventilation
        else:
            co2_decay = self.co2_natural_decay * time_step_hours
            
            co2_human = occupants * self.co2_per_person * time_step_hours
            
            co2_ventilation = 0
            
            if ventilation_mode == 'natural':
                co2_ventilation = self.ventilation_rates["natural"] * time_step_hours
            
            elif ventilation_mode == 'mechanical' and ventilation_speed in ['low', 'medium', 'max']:
                vent_key = f"mechanical_{ventilation_speed}"
                co2_ventilation = self.ventilation_rates[vent_key] * time_step_hours
            
            co2_net_change = co2_human - co2_decay - co2_ventilation
        
        self.co2 = max(self.outdoor_co2, self.co2 + co2_net_change)
        
        temp_ventilation = 0
        humidity_ventilation = 0
        
        if ventilation_mode == 'natural':
            temp_ventilation = self.temp_ventilation_effects["natural"] * time_step_hours
            humidity_ventilation = self.humidity_ventilation_effects["natural"] * time_step_hours
        
        elif ventilation_mode == 'mechanical' and ventilation_speed in ['low', 'medium', 'max']:
            vent_key = f"mechanical_{ventilation_speed}"
            temp_ventilation = self.temp_ventilation_effects[vent_key] * time_step_hours
            humidity_ventilation = self.humidity_ventilation_effects[vent_key] * time_step_hours
        
        temp_net_change = (outdoor_temp - self.temperature) * self.temp_natural_decay * time_step_hours
        
        if ventilation_mode in ['natural', 'mechanical']:
            if outdoor_temp < self.temperature:
                temp_net_change -= temp_ventilation
            else:
                temp_net_change += temp_ventilation
        
        human_heat = 0.2 * occupants * time_step_hours
        
        self.temperature += temp_net_change + human_heat
        
        humidity_outdoor_diff = (self.outdoor_humidity - self.humidity) * 0.1 * time_step_hours
        humidity_human = 2.0 * occupants * time_step_hours
        
        if ventilation_mode in ['natural', 'mechanical']:
            if self.outdoor_humidity < self.humidity:
                humidity_ventilation = -humidity_ventilation
        
        self.humidity += humidity_outdoor_diff + humidity_human + humidity_ventilation
        self.humidity = max(10, min(95, self.humidity))
        
        self._record_state(occupants=occupants, 
                        ventilation_mode=ventilation_mode, 
                        ventilation_speed=ventilation_speed)
        
        return self.get_current_state()
    
    def _record_state(self, occupants=0, ventilation_mode=None, ventilation_speed=None):
        self.history.append({
            'timestamp': self.current_time.isoformat(),
            'co2': round(self.co2, 1),
            'temperature': round(self.temperature, 1),
            'humidity': round(self.humidity, 1),
            'occupants': occupants,
            'ventilation_mode': ventilation_mode,
            'ventilation_speed': ventilation_speed
        })
        
        if len(self.history) > 10000:
            self.history = self.history[-5000:]
    
    def get_current_state(self):
        return {
            'timestamp': self.current_time.isoformat(),
            'co2': round(self.co2, 1),
            'temperature': round(self.temperature, 1),
            'humidity': round(self.humidity, 1),
            'outdoor_temperature': round(self._get_outdoor_temperature(), 1),
            'outdoor_humidity': self.outdoor_humidity,
            'outdoor_co2': self.outdoor_co2
        }
    
    def get_sensor_data(self):
        return {
            "timestamp": self.current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "scd41": {
                "co2": round(self.co2),
                "temperature": round(self.temperature, 1),
                "humidity": round(self.humidity, 1)
            },
            "bmp280": {
                "temperature": round(self.temperature, 1), 
                "pressure": 1013.25
            }
        }
    
    def reset(self, initial_co2=None, initial_temp=None, initial_humidity=None):
        if initial_co2 is not None:
            self.co2 = initial_co2
        if initial_temp is not None:
            self.temperature = initial_temp
        if initial_humidity is not None:
            self.humidity = initial_humidity
        
        self.history = []
        self._record_state()
        
        logger.info(f"Environment reset: CO2={self.co2}ppm, "
                   f"Temp={self.temperature}°C, "
                   f"Humidity={self.humidity}%")
    
    def export_history(self):
        return self.history