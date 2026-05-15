import bpy
import os

# Путь к папке с .m3 файлами
m3_folder = "C:\\Users\\0\\Documents\\StarCraft II\\Exported_Models\\mods\\liberty.sc2mod\\base.sc2assets\\assets\\units\\zerg"
blend_folder = "C:\\Users\\0\\Documents\\StarCraft II\\Exported_Models\\blend_models"

for dirs in os.listdir(m3_folder):
    for m3_file in os.listdir(os.path.join(m3_folder, dirs)):
        if not m3_file.endswith(".m3"):
            continue

        # Очистка сцены (опционально)
        bpy.ops.wm.read_factory_settings(use_empty=True)

        # Импорт .m3 через ваш плагин
        m3_import_op = getattr(bpy.ops.m3, 'import')
        bpy.ops.m3.m3_import_op(filepath=os.path.join(m3_folder, m3_file))

        # Сохраняем как .blend в ту же папку
        blend_path = os.path.join(blend_folder, m3_file.replace(".m3", ".blend"))
        bpy.ops.wm.save_as_mainfile(filepath=blend_path)