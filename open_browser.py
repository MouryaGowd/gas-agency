"""Wait until the server answers, then open it in the default browser (used by run.bat)."""
import sys
import time
import urllib.error
import urllib.request
import webbrowser

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/"
deadline = time.time() + 240  # first start generates data and trains the model
while time.time() < deadline:
    try:
        urllib.request.urlopen(url, timeout=2)
        webbrowser.open(url)
        break
    except urllib.error.HTTPError:  # server is up (any HTTP answer counts)
        webbrowser.open(url)
        break
    except (urllib.error.URLError, OSError):
        time.sleep(1)
