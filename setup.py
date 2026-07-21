from setuptools import setup, find_packages

setup(
    name="blooms-in-gnome",
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/locale/blooms-in-gnome.mo", []),  # installed manually via install.sh
    ],
    install_requires=[
        "PyGObject>=3.48",
        "requests>=2.31",
        "cryptography>=41.0",
        "coincurve>=21.0",
        "fusepy>=3.0",
        "pystray>=0.19",
        "pillow>=10.0",
        "cairosvg>=2.9",
        "websocket-client>=1.6",
        "keyring>=24.0",
    ],
    entry_points={
        "console_scripts": [
            "blooms-mount=blooms_in_gnome.__main__:main",
            "blooms-tray=blooms_in_gnome.__main__:tray_main",
        ],
    },
    python_requires=">=3.10",
)
