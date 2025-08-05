import os
import sys
import winreg as reg

cwd = os.getcwd()
python_exe = sys.executable

key_path = r"Directory\\Background\\shell\\ImxUpload"

key = reg.CreateKeyEx(reg.HKEY_CLASSES_ROOT, key_path)

reg.SetValueEx(key, '', 0, reg.REG_SZ, '&Upload to Imx.to')

key1 = reg.CreateKeyEx(key, r"command")
reg.SetValueEx(key1, '', 0, reg.REG_SZ, f'"{python_exe}" "{cwd}\\imxup.py"')






key_path2 = r"Directory\\Shell\\ImxUpload"

key2 = reg.CreateKeyEx(reg.HKEY_CLASSES_ROOT, key_path2)

reg.SetValueEx(key2, '', 0, reg.REG_SZ, '&Upload to Imx.to')

key3 = reg.CreateKeyEx(key2, r"command")

reg.SetValueEx(key3, '', 0, reg.REG_SZ, f'"{python_exe}" "{cwd}\\imxup.py" %*')

