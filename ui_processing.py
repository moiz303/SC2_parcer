import json


def ui_progress(stage, progress, message=""):
    """Микро-хелпер для передачи сообщений с backend на frontend"""
    print(
        "__UI__" +
        json.dumps({
            "stage": stage,
            "progress": progress,
            "message": message
        }),
        flush=True
    )
