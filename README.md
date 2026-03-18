# Digital Photoframe

<img width="4000" height="3000" alt="image" src="https://github.com/user-attachments/assets/0ac0abed-0571-4148-a99c-2daa23604304" />

A robust, Kivy-based Android application designed to turn legacy Android tablets into smart digital photoframes. It features Google Drive folder synchronization, local texture caching to prevent RAM overflow on older hardware, and OpenWeather API integration.

## Features
* **Google Drive Sync:** Automatically downloads and updates photos from a specified Drive folder.
* **Intelligent Caching:** Implements neighbor-only texture caching to run smoothly on low-RAM devices.
* **Weather & Clock:** Real-time overlay using the OpenWeather API.
* **Home App Capable:** Includes intent filters to act as the default Android Launcher (Kiosk mode).

## Local Development
This project uses `uv` for dependency management.

1.  Clone the repository.
2.  Create a "secrets.json" with your OpenWeatherMap token, Google Drive folder id, and Google service account key .json filename:
    ```
    {
    "open-weather-key" : "",
    "google-drive-folder-id" : "",
    "google-drive-service-key-json" : ""
    }
    ```
4.  Run locally:
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
