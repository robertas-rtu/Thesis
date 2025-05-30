# BMP280 temperature and pressure sensor interface
import time
import smbus2
import logging

logger = logging.getLogger(__name__)

# BMP280 register addresses
BMP280_TEMP_XLSB = 0xFC
BMP280_TEMP_LSB  = 0xFB
BMP280_TEMP_MSB  = 0xFA
BMP280_PRESS_XLSB = 0xF9
BMP280_PRESS_LSB  = 0xF8
BMP280_PRESS_MSB  = 0xF7

# Control registers
BMP280_CONFIG     = 0xF5
BMP280_CTRL_MEAS  = 0xF4
BMP280_STATUS     = 0xF3
BMP280_RESET      = 0xE0
BMP280_CHIP_ID    = 0xD0
BMP280_CALIB_DATA = 0x88

class BMP280:
    # Interface for the BMP280 temperature and pressure sensor
    
    def __init__(self, bus_number, address):
        # I2C setup
        self.bus = smbus2.SMBus(bus_number)
        self.address = address

        # Check chip ID
        chip_id = self.bus.read_byte_data(self.address, BMP280_CHIP_ID)
        if chip_id != 0x58:
            raise Exception(f"Unexpected BMP280 chip ID: {chip_id}")

        # Load calibration data
        self.cal_data = {}
        cal_data = [self.bus.read_byte_data(self.address, BMP280_CALIB_DATA + i) for i in range(24)]
        
        # Parse temperature calibration coefficients
        self.cal_data['dig_T1'] = cal_data[1] << 8 | cal_data[0]
        self.cal_data['dig_T2'] = self._get_signed_short(cal_data[3] << 8 | cal_data[2])
        self.cal_data['dig_T3'] = self._get_signed_short(cal_data[5] << 8 | cal_data[4])
        
        # Parse pressure calibration coefficients
        self.cal_data['dig_P1'] = cal_data[7] << 8 | cal_data[6]
        self.cal_data['dig_P2'] = self._get_signed_short(cal_data[9] << 8 | cal_data[8])
        self.cal_data['dig_P3'] = self._get_signed_short(cal_data[11] << 8 | cal_data[10])
        self.cal_data['dig_P4'] = self._get_signed_short(cal_data[13] << 8 | cal_data[12])
        self.cal_data['dig_P5'] = self._get_signed_short(cal_data[15] << 8 | cal_data[14])
        self.cal_data['dig_P6'] = self._get_signed_short(cal_data[17] << 8 | cal_data[16])
        self.cal_data['dig_P7'] = self._get_signed_short(cal_data[19] << 8 | cal_data[18])
        self.cal_data['dig_P8'] = self._get_signed_short(cal_data[21] << 8 | cal_data[20])
        self.cal_data['dig_P9'] = self._get_signed_short(cal_data[23] << 8 | cal_data[22])

        # Configure sensor
        # Temperature x2, pressure x16 oversampling, normal mode
        self.bus.write_byte_data(self.address, BMP280_CTRL_MEAS, 0b01110111)
        
        # 500ms standby, IIR filter x16, disable 3-wire SPI
        self.bus.write_byte_data(self.address, BMP280_CONFIG, 0b10100000)
        
        # Wait for config
        time.sleep(0.5)

    def _get_signed_short(self, value):
        # Convert unsigned 16-bit to signed short
        if value & (1 << 15):
            value -= (1 << 16)
        return value

    def read_raw_data(self):
        # Read raw sensor data
        # Read 6 bytes: pressure + temperature
        data = [self.bus.read_byte_data(self.address, BMP280_PRESS_MSB + i) for i in range(6)]
        
        # Combine into 20-bit values
        pressure = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        temperature = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
        
        return temperature, pressure

    def read_temperature(self):
        # Read temperature in degrees Celsius
        raw_temp, _ = self.read_raw_data()
        
        # Apply temperature calibration
        var1 = ((raw_temp / 16384.0 - self.cal_data['dig_T1'] / 1024.0) * self.cal_data['dig_T2'])
        var2 = ((raw_temp / 131072.0 - self.cal_data['dig_T1'] / 8192.0) *
                (raw_temp / 131072.0 - self.cal_data['dig_T1'] / 8192.0) * self.cal_data['dig_T3'])
        
        # Store t_fine for pressure calc
        self.t_fine = var1 + var2
        
        temperature = self.t_fine / 5120.0
        return temperature

    def read_pressure(self):
        # Read barometric pressure in hPa
        _, raw_pressure = self.read_raw_data()
        
        # Need t_fine from temperature reading
        self.read_temperature()
        
        # Apply pressure calibration
        var1 = self.t_fine / 2.0 - 64000.0
        var2 = var1 * var1 * self.cal_data['dig_P6'] / 32768.0
        var2 += var1 * self.cal_data['dig_P5'] * 2.0
        var2 = var2 / 4.0 + self.cal_data['dig_P4'] * 65536.0
        var1 = (self.cal_data['dig_P3'] * var1 * var1 / 524288.0 +
                self.cal_data['dig_P2'] * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.cal_data['dig_P1']
        
        # Avoid divide by zero
        if var1 == 0:
            return 0
            
        pressure = 1048576.0 - raw_pressure
        pressure = (pressure - var2 / 4096.0) * 6250.0 / var1
        var1 = self.cal_data['dig_P9'] * pressure * pressure / 2147483648.0
        var2 = pressure * self.cal_data['dig_P8'] / 32768.0
        pressure += (var1 + var2 + self.cal_data['dig_P7']) / 16.0
        
        # Convert to hPa
        return pressure / 100.0