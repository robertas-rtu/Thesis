"""Wake-on-LAN (WoL) functionality for waking network devices."""
# utils/wol.py
import logging
from wakeonlan import send_magic_packet
import socket
import subprocess
import time

logger = logging.getLogger(__name__)

def wake_device(mac_address):
    """Send a Wake-on-LAN magic packet to wake a device."""
    try:
        mac = mac_address.replace(':', '').replace('-', '').lower()
        mac = ':'.join(mac[i:i+2] for i in range(0, 12, 2))
        
        logger.info(f"Sending WoL magic packet to {mac}")
        send_magic_packet(mac)
        return True
    except Exception as e:
        logger.error(f"Error sending WoL packet to {mac_address}: {e}")
        return False

def check_device_responds(ip_address, timeout=3):
    """Check if a device responds to ping after wake-up attempt."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip_address],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout+1
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.debug(f"Ping timeout for {ip_address}")
        return False
    except Exception as e:
        logger.error(f"Error pinging {ip_address}: {e}")
        return False

def wake_and_check(mac_address, ip_address, max_attempts=2):
    """Wake a device and check if it responds."""
    # Check if already responding
    if check_device_responds(ip_address):
        logger.debug(f"Device {ip_address} already responding")
        return True
    
    # Attempt to wake
    for attempt in range(max_attempts):
        logger.debug(f"Wake attempt {attempt+1}/{max_attempts} for {mac_address}")
        
        wake_device(mac_address)
        
        for i in range(3):
            time.sleep(1)
            if check_device_responds(ip_address):
                logger.info(f"Successfully woke device {mac_address} ({ip_address})")
                return True
    
    logger.debug(f"Failed to wake device {mac_address} after {max_attempts} attempts")
    return False