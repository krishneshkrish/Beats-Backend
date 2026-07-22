import os
import platform
import subprocess
import logging
import httpx

logger = logging.getLogger("beats.pot")

def get_binary_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    
    if system == "windows":
        return "bgutil-pot-windows-x86_64.exe"
    elif system == "linux":
        if "aarch64" in machine or "arm" in machine:
            return "bgutil-pot-linux-aarch64"
        else:
            return "bgutil-pot-linux-x86_64"
    elif system == "darwin":
        if "arm" in machine or "aarch64" in machine:
            return "bgutil-pot-macos-aarch64"
        else:
            return "bgutil-pot-macos-x86_64"
    return None

VERSION = "v0.8.1"
_process = None

def get_binary_path() -> str:
    name = get_binary_name()
    if not name:
        return None
    # Save the binary in the root directory for execution simplicity
    return os.path.join(os.getcwd(), name)

def download_binary() -> bool:
    name = get_binary_name()
    if not name:
        logger.warning(f"⚠️  Unsupported platform/architecture for PO Token Provider: {platform.system()} {platform.machine()}")
        return False
    
    path = get_binary_path()
    if os.path.exists(path):
        return True
        
    url = f"https://github.com/jim60105/bgutil-ytdlp-pot-provider-rs/releases/download/{VERSION}/{name}"
    logger.info(f"📥 Downloading PO Token Provider binary from {url}...")
    try:
        # Use httpx to follow redirects and download
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            response = client.get(url)
            response.raise_for_status()
            with open(path, "wb") as f:
                f.write(response.content)
        
        # Make it executable on non-Windows systems
        if system != "windows":
            os.chmod(path, 0o755)
        logger.info(f"✅ Successfully downloaded and prepared PO Token Provider at {path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to download PO Token Provider binary: {e}")
        return False

def start_provider():
    global _process
    if _process is not None:
        return
        
    if not download_binary():
        return
        
    path = get_binary_path()
    if not path or not os.path.exists(path):
        return
        
    logger.info("🚀 Starting background PO Token Provider...")
    try:
        # Hide command window on Windows
        creationflags = 0
        if platform.system().lower() == "windows":
            creationflags = subprocess.CREATE_NO_WINDOW
            
        import time
        _process = subprocess.Popen(
            [path, "server", "--port", "4416", "--host", "127.0.0.1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
            text=True
        )
        # Give it a second to initialize/fail
        time.sleep(1.0)
        ret = _process.poll()
        if ret is not None:
            stdout_data, stderr_data = _process.communicate()
            logger.error(f"❌ Background PO Token Provider exited immediately with code {ret}")
            logger.error(f"Stdout: {stdout_data.strip()}")
            logger.error(f"Stderr: {stderr_data.strip()}")
            _process = None
        else:
            logger.info("✅ Background PO Token Provider running on port 4416")
    except Exception as e:
        logger.error(f"❌ Failed to start background PO Token Provider: {e}")

def stop_provider():
    global _process
    if _process is not None:
        logger.info("Stopping background PO Token Provider...")
        try:
            _process.terminate()
            _process.wait(timeout=5)
        except Exception as e:
            logger.error(f"Error stopping PO Token Provider: {e}")
        finally:
            _process = None
