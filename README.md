# Digital Photoframe

<img width="1002" height="789" alt="image" src="https://github.com/user-attachments/assets/7f096c81-1ceb-42d2-83e9-c24c71470ebb" />


A robust, Kivy-based Android application designed to turn legacy Android tablets into smart digital photoframes. It features Google Drive folder synchronization, local texture caching to prevent RAM overflow on older hardware, and OpenWeather API integration.

## Features
* **Google Drive Sync:** Automatically downloads and updates photos from a specified Drive folder.
* **Intelligent Caching:** Implements neighbor-only texture caching to run smoothly on low-RAM devices.
* **Weather & Clock:** Real-time overlay using the OpenWeather API.
* **Home App Capable:** Includes intent filters to act as the default Android Launcher (Kiosk mode).

## Local Development
This project uses `uv` for dependency management.

1.  Clone the repository.
2.  Place your Google Service Account key in the root directory (must match the `service_acc` filename in `DEFAULT_CFG`).
3.  Run locally:
    ```bash
    uv run python main.py
    ```

## Android Build Instructions
The Android APK is compiled using Buildozer via WSL (Windows Subsystem for Linux).

1.  Activate your Linux virtual environment.
2.  Connect your Android device via ADB.
3.  Build and deploy:
    ```bash
    buildozer android debug deploy run
    ```
