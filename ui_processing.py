import json
import sys


def ui_progress(stage, progress, message=""):
    """Микро-хелпер для передачи сообщений с backend на frontend"""
    sys.stdout.write(
        "__UI__" +
        json.dumps({
            "stage": stage,
            "progress": progress,
            "message": message
        }) + "\n"
    )
    sys.stdout.flush()
