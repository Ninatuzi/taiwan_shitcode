# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

block_cipher = None

# collect_all 會一次收齊 PySide6 的 datas / binaries / hiddenimports
pyside6_datas, pyside6_binaries, pyside6_hidden = collect_all('PySide6')

a = Analysis(
    ['launcher_gui.py'],
    pathex=['.'],
    binaries=[
        *pyside6_binaries,
    ],
    datas=[
        ('frontend/dist', 'frontend/dist'),
        ('backend', 'backend'),
        *pyside6_datas,
    ],
    hiddenimports=[
        *pyside6_hidden,
        # uvicorn
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # fastapi / starlette
        'fastapi',
        'fastapi.routing',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.staticfiles',
        'fastapi.responses',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.staticfiles',
        'starlette.responses',
        'starlette.requests',
        'starlette.datastructures',
        'starlette.exceptions',
        'starlette.types',
        # data & AI
        'anthropic',
        'pypdf',
        'pydantic',
        # misc
        'email.mime.text',
        'email.mime.multipart',
        'h11',
        'anyio',
        'anyio._backends._asyncio',
        'sniffio',
        'httpx',
        'httpcore',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BMS-FW-Validation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BMS-FW-Validation',
)
