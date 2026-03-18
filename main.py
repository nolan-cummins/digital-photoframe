import os
import json
import threading
import time
import requests
import certifi
import webbrowser
import shutil
import stat
import logging
import random
import re
from collections import deque

os.environ['SSL_CERT_FILE'] = certifi.where()

from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import AsyncImage
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.gridlayout import GridLayout
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.spinner import Spinner
from kivy.animation import Animation
from kivy.clock import Clock, mainthread
from kivy.config import Config
from kivy.graphics import Color, Rectangle
from kivy.utils import get_color_from_hex
from kivy.cache import Cache
from kivy.logger import Logger
from kivy.utils import platform

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- PLATFORM SPECIFIC SETUP ---
if platform == 'android':
    from jnius import autoclass
    from android.runnable import run_on_ui_thread
    from android.permissions import request_permissions, Permission
    from android.storage import primary_external_storage_path

    PHOTO_DIR = os.path.join(primary_external_storage_path(), 'digital_photoframe')

    @run_on_ui_thread
    def keep_screen_on():
        try:
            Activity = autoclass('org.kivy.android.PythonActivity').mActivity
            LayoutParams = autoclass('android.view.WindowManager$LayoutParams')
            Activity.getWindow().addFlags(LayoutParams.FLAG_KEEP_SCREEN_ON)
        except Exception as e:
            Logger.error(f"WakeLock Error: {e}")
else:
    def keep_screen_on(): pass
    Config.set('graphics', 'width', '1280')
    Config.set('graphics', 'height', '800')
    PHOTO_DIR = os.path.abspath('./digital_photoframe')

APP_VERSION = "1.0.0"
GITHUB_REPO = "nolan-cummins/digital-photoframe"

with open("secrets.json", 'r') as f:
    secrets = json.load(f)

DEFAULT_CFG = {
    'time_mode': 'auto', 'city': 'Champaign', 'region': 'IL', 'tz_offset': '-5', 'format_24h': False,
    'units': 'imperial', 'weather_fmt': '{temp}°F | {wind}mph wind | {clouds}',
    'ui_opacity': 0.8, 'show_ui': True, 'text_color': '#FFFFFF', 'stroke_color': '#000000',
    'slide_interval': 15, 'sync_interval': 120, 'weather_interval': 600, 'fade_time': 1.5,
    'nav_mode': 'swipe', 'fast_manual': False, 'brightness': 1.0, 'startup_delay': 5,
    'playback_mode': 'sorted',
    'api_key': secrets["open-weather-key"], 'folder_id': secrets["google-drive-folder-id"],
    'service_acc': secrets["google-drive-service-key-json"],
    'selected_folder': 'Base', 'show_console': False
}

class UILogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
    def emit(self, record):
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            pass

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

class PhotoFrameApp(App):
    def build(self):
        self.cfg = DEFAULT_CFG.copy()
        self.cfg_path = os.path.join(PHOTO_DIR, 'config.json')

        keep_screen_on()

        self.root = FloatLayout()
        
        with self.root.canvas.before:
            Color(0, 0, 0, 1)
            self.bg_rect = Rectangle(size=self.root.size, pos=self.root.pos)
            self.overlay_color = Color(1, 1, 1, self.cfg['brightness'])
            
        self.root.bind(pos=self._update_rect, size=self._update_rect)
        self.root.bind(on_touch_down=self._on_touch_down, on_touch_up=self._on_touch_up)

        self.img1 = AsyncImage(source='', opacity=0, fit_mode="cover", nocache=True)
        self.img2 = AsyncImage(source='', opacity=0, fit_mode="cover", nocache=True)
        self.root.add_widget(self.img1)
        self.root.add_widget(self.img2)
        
        self.img1.bind(on_load=self._on_img_loaded, on_error=self._on_img_error)
        self.img2.bind(on_load=self._on_img_loaded, on_error=self._on_img_error)
        
        self.time_label = Label(font_size='50sp', pos_hint={'x': 0.03, 'y': 0.10}, size_hint=(None, None), halign='left')
        self.weather_label = Label(font_size='22sp', pos_hint={'x': 0.03, 'y': 0.05}, size_hint=(None, None), halign='left')
        for lbl in (self.time_label, self.weather_label):
            lbl.bind(texture_size=lbl.setter('size'))
            self.root.add_widget(lbl)
            
        self.console_lines = deque(maxlen=20)
        self.console_label = Label(
            text="System Initializing...", font_size='12sp', halign='left', valign='top',
            size_hint=(1, 0.4), pos_hint={'top': 1, 'x': 0}, color=(0, 1, 0, 1), padding=(10, 10)
        )
        self.console_label.bind(size=self.console_label.setter('text_size'))
        with self.console_label.canvas.before:
            self.console_bg = Color(0, 0, 0, 0.7)
            self.console_rect = Rectangle(size=self.console_label.size, pos=self.console_label.pos)
        
        def _update_console_rect(instance, value):
            self.console_rect.pos = instance.pos
            self.console_rect.size = instance.size
        self.console_label.bind(pos=_update_console_rect, size=_update_console_rect)
        self.root.add_widget(self.console_label)
        
        self._apply_ui_styles()

        ui_handler = UILogHandler(self._log_to_ui)
        ui_handler.setFormatter(logging.Formatter('[%(levelname)-7s] %(message)s'))
        Logger.addHandler(ui_handler)
        
        urllib3_logger = logging.getLogger('urllib3')
        urllib3_logger.setLevel(logging.DEBUG)
        urllib3_logger.addHandler(ui_handler)

        self.settings_btn = Button(size_hint=(0.1, 0.1), pos_hint={'right': 1, 'y': 0}, background_color=(0,0,0,0))
        self.settings_btn.bind(on_release=self._open_settings)
        self.root.add_widget(self.settings_btn)

        self.active_img = self.img1
        self._target_img = None
        self._swipe_start_x = 0
        self.photo_index = -1
        self._state = 'IDLE'
        self.photos = []
        self._current_dir = None
        self._current_manual_flag = False 

        if platform == 'android':
            request_permissions([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE], self._on_permissions_granted)
        else:
            self._on_permissions_granted([], [True])

        return self.root

    def _on_permissions_granted(self, permissions, grants):
        Clock.schedule_once(lambda dt: self._finish_startup(grants), 0)

    def _finish_startup(self, grants):
        if not all(grants):
            Logger.error("Permissions denied! Cannot run photoframe.")
            self.console_label.text = "STORAGE PERMISSION DENIED.\nPlease allow in Settings to continue."
            return

        os.makedirs(PHOTO_DIR, exist_ok=True)
        self.cfg = self._load_cfg()
        self._apply_ui_styles()

        threading.Thread(target=self._sync_engine_loop, daemon=True).start()
        
        Clock.schedule_interval(self._update_time, 1)
        Clock.schedule_once(self._trigger_weather, 1) 
        self.weather_event = Clock.schedule_interval(self._trigger_weather, self.cfg['weather_interval'])
        self.slide_event = Clock.schedule_interval(self._auto_slide, self.cfg['slide_interval'])
        Clock.schedule_once(lambda dt: self._next_slide(1), self.cfg['startup_delay'])
        
        Clock.schedule_once(lambda dt: self._check_for_updates(manual=False), 10)
        Clock.schedule_interval(lambda dt: self._check_for_updates(manual=False), 86400)
        Logger.info("Boot complete.")

    @mainthread
    def _log_to_ui(self, msg):
        self.console_lines.append(msg)
        self.console_label.text = "\n".join(self.console_lines)

    def _load_cfg(self):
        if os.path.exists(self.cfg_path):
            with open(self.cfg_path, 'r') as f:
                return {**DEFAULT_CFG, **json.load(f)}
        return DEFAULT_CFG.copy()

    def _save_cfg(self):
        with open(self.cfg_path, 'w') as f:
            json.dump(self.cfg, f)

    def _apply_ui_styles(self):
        tc = get_color_from_hex(self.cfg['text_color'])
        sc = get_color_from_hex(self.cfg['stroke_color'])
        op = self.cfg['ui_opacity'] if self.cfg['show_ui'] else 0
        
        for lbl in (self.time_label, self.weather_label):
            lbl.color = tc
            lbl.outline_color = sc
            lbl.opacity = op
            
        self.overlay_color.a = self.cfg['brightness']
        self.console_label.opacity = 1 if self.cfg.get('show_console') else 0
        self.console_bg.a = 0.7 if self.cfg.get('show_console') else 0

    def _update_rect(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def _on_touch_down(self, instance, touch):
        if self.settings_btn.collide_point(*touch.pos): 
            return False

        if self.time_label.collide_point(*touch.pos) or self.weather_label.collide_point(*touch.pos):
            target_op = 0 if self.time_label.opacity > 0 else self.cfg['ui_opacity']
            self.cfg['show_ui'] = (target_op > 0)
            Animation(opacity=target_op, duration=0.5).start(self.time_label)
            Animation(opacity=target_op, duration=0.5).start(self.weather_label)
            self._save_cfg()
            return True

        if self._state != 'IDLE' and not self.cfg['fast_manual']: 
            return True

        if self.cfg['nav_mode'] == 'tap':
            direction = -1 if touch.x < self.root.width / 2 else 1
            self._next_slide(direction, manual=True)
        else:
            self._swipe_start_x = touch.x
        return False

    def _on_touch_up(self, instance, touch):
        if self.cfg['nav_mode'] == 'swipe' and self._swipe_start_x:
            dx = touch.x - self._swipe_start_x
            if abs(dx) > 50:
                self._next_slide(-1 if dx > 0 else 1, manual=True)
            self._swipe_start_x = 0
        return False

    def _auto_slide(self, dt):
        self._next_slide(1)

    def _get_active_dir(self):
        sel = self.cfg.get('selected_folder', 'Base')
        return PHOTO_DIR if sel == 'Base' else os.path.join(PHOTO_DIR, sel)
        
    def _get_photos_in_dir(self, directory):
        if not os.path.exists(directory): return []
        return [
            os.path.normpath(os.path.abspath(os.path.join(directory, f))) 
            for f in os.listdir(directory) 
            if os.path.isfile(os.path.join(directory, f)) and f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ]

    def _refresh_playlist(self, target_dir):
        raw_photos = self._get_photos_in_dir(target_dir)
        raw_photos.sort(key=natural_sort_key)
        
        if self.cfg.get('playback_mode') == 'random':
            random.shuffle(raw_photos)
            
        self.photos = raw_photos
        self.photo_index = -1

    def _next_slide(self, direction, manual=False):
        if self._state != 'IDLE' and not self.cfg['fast_manual']: 
            return
        
        target_dir = self._get_active_dir()
        
        if self._current_dir != target_dir or not self.photos:
            self._current_dir = target_dir
            self._refresh_playlist(target_dir)

            if not self.photos and target_dir != PHOTO_DIR:
                self.cfg['selected_folder'] = 'Base'
                self._save_cfg()
                target_dir = PHOTO_DIR
                self._current_dir = target_dir
                self._refresh_playlist(target_dir)

        if not self.photos: 
            return

        self.photo_index = (self.photo_index + direction) % len(self.photos)
        target_source = self.photos[self.photo_index]

        self._target_img = self.img2 if self.active_img == self.img1 else self.img1
        self._current_manual_flag = manual
        
        Animation.cancel_all(self.img1)
        Animation.cancel_all(self.img2)

        self._state = 'LOADING'
        Clock.unschedule(self._force_unlock)
        Clock.schedule_once(self._force_unlock, 3.0) 

        if self._target_img.source == target_source:
            self._start_fade()
        else:
            self._target_img.source = target_source

    def _on_img_loaded(self, instance, *args):
        if instance == self._target_img and self._state == 'LOADING':
            self._start_fade()

    def _on_img_error(self, instance, *args):
        if instance == self._target_img:
            Logger.warning(f"Failed to load image: {instance.source}")
            self._force_unlock()

    def _start_fade(self, *args):
        Clock.unschedule(self._force_unlock)
        old_img = self.active_img
        self.active_img = self._target_img
        
        duration = 0.0 if self._current_manual_flag and self.cfg['fast_manual'] else self.cfg['fade_time']
        
        if duration > 0:
            self._state = 'ANIMATING'
            Animation(opacity=0, duration=duration).start(old_img)
            anim_in = Animation(opacity=1, duration=duration)
            anim_in.bind(on_complete=self._on_fade_complete)
            anim_in.start(self.active_img)
        else:
            old_img.opacity = 0
            self.active_img.opacity = 1
            self._on_fade_complete()

    def _on_fade_complete(self, *args):
        self._state = 'IDLE'
        self._purge_cache()

    def _force_unlock(self, *args):
        self._state = 'IDLE'
        self.active_img.opacity = 1
        self._purge_cache()

    def _purge_cache(self):
        if not self.photos: return
        prev_idx = (self.photo_index - 1) % len(self.photos)
        next_idx = (self.photo_index + 1) % len(self.photos)
        keep_paths = {
            self.photos[self.photo_index], 
            self.photos[prev_idx], 
            self.photos[next_idx]
        }
        for cache_name in ['kv.image', 'kv.texture']:
            cache_keys = list(Cache._objects.get(cache_name, {}).keys())
            for key in cache_keys:
                if key not in keep_paths:
                    Cache.remove(cache_name, key)

    def _update_time(self, *args):
        fmt = "%H:%M" if self.cfg['format_24h'] else "%I:%M %p"
        if self.cfg['time_mode'] == 'manual':
            try:
                t = time.gmtime(time.time() + float(self.cfg['tz_offset']) * 3600)
                self.time_label.text = time.strftime(fmt, t)
            except ValueError:
                pass
        else:
            self.time_label.text = time.strftime(fmt)

    def _trigger_weather(self, *args):
        threading.Thread(target=self._fetch_weather, daemon=True).start()

    def _fetch_weather(self):
        try:
            city, region = self.cfg['city'], self.cfg['region']
            if self.cfg['time_mode'] == 'auto':
                geo = requests.get("http://ip-api.com/json/", timeout=5).json()
                if geo.get('status') == 'success':
                    city, region = geo['city'], geo['region']

            url = f"https://api.openweathermap.org/data/2.5/weather?q={city},{region},US&appid={self.cfg['api_key']}&units={self.cfg['units']}"
            w_data = requests.get(url, timeout=5).json()
            
            temp = int(w_data['main']['temp'])
            wind = int(w_data['wind']['speed'])
            clouds = w_data['weather'][0]['description'].title()
            
            res = self.cfg['weather_fmt'].format(temp=temp, wind=wind, clouds=clouds)
            self._update_weather_ui(f"{city}: {res}")
        except Exception as e:
            Logger.error(f"Weather: Error fetching data - {e}")
            self._update_weather_ui("Weather Offline")

    @mainthread
    def _update_weather_ui(self, text):
        self.weather_label.text = text

    def _sync_engine_loop(self):
        while True:
            self._run_sync_pass(manual=False)
            time.sleep(self.cfg['sync_interval'])

    def _run_sync_pass(self, manual=False):
        Logger.info("Sync: Starting Drive Sync Pass...")
        try:
            creds = service_account.Credentials.from_service_account_file(self.cfg['service_acc'], scopes=['https://www.googleapis.com/auth/drive.readonly'])
            service = build('drive', 'v3', credentials=creds, cache_discovery=False)
            
            queue = deque([(self.cfg['folder_id'], "")])
            valid_local_paths = set()
            valid_local_dirs = set([os.path.normpath(os.path.abspath(PHOTO_DIR))])

            while queue:
                current_id, local_path = queue.popleft()
                curr_dir = os.path.join(PHOTO_DIR, local_path)
                os.makedirs(curr_dir, exist_ok=True)

                page_token = None
                while True:
                    results = service.files().list(
                        q=f"'{current_id}' in parents and (mimeType contains 'image/' or mimeType = 'application/vnd.google-apps.folder') and trashed=false",
                        fields="nextPageToken, files(id, name, mimeType)",
                        pageToken=page_token,
                        pageSize=1000
                    ).execute()
                    
                    for item in results.get('files', []):
                        if item['mimeType'] == 'application/vnd.google-apps.folder':
                            new_dir = os.path.join(local_path, item['name'])
                            queue.append((item['id'], new_dir))
                            valid_local_dirs.add(os.path.normpath(os.path.abspath(os.path.join(PHOTO_DIR, new_dir))))
                        else:
                            target_path = os.path.normpath(os.path.abspath(os.path.join(curr_dir, item['name'])))
                            valid_local_paths.add(target_path)
                            
                            if not os.path.exists(target_path):
                                Logger.info(f"Sync: Downloading {item['name']}")
                                request = service.files().get_media(fileId=item['id'])
                                tmp_path = target_path + ".tmp"
                                with open(tmp_path, 'wb') as f:
                                    downloader = MediaIoBaseDownload(f, request)
                                    done = False
                                    while not done: _, done = downloader.next_chunk()
                                os.rename(tmp_path, target_path)

                    page_token = results.get('nextPageToken')
                    if not page_token: break

            def force_rm(func, path, exc_info):
                os.chmod(path, stat.S_IWRITE)
                func(path)

            for root, dirs, files in os.walk(PHOTO_DIR, topdown=False):
                norm_root = os.path.normpath(os.path.abspath(root))
                if norm_root not in valid_local_dirs:
                    Logger.info(f"Sync: Deleting removed folder {norm_root}")
                    try: shutil.rmtree(norm_root, onerror=force_rm)
                    except OSError as e: Logger.error(f"Sync: Failed to delete dir {norm_root}: {e}")
                    continue

                for f in files:
                    full_path = os.path.normpath(os.path.abspath(os.path.join(root, f)))
                    if full_path not in valid_local_paths and not full_path.endswith('.tmp') and f != 'config.json':
                        Logger.info(f"Sync: Deleting removed file {full_path}")
                        try: os.remove(full_path)
                        except OSError as e: Logger.error(f"Sync: Failed to delete {full_path}: {e}")
                            
            Logger.info("Sync: Drive Sync Pass Complete.")
            self._on_sync_success(manual)
            
        except Exception as e:
            Logger.error(f"Sync: Pass Error - {e}")

    @mainthread
    def _on_sync_success(self, manual):
        folders = ['Base'] + [d for d in os.listdir(PHOTO_DIR) if os.path.isdir(os.path.join(PHOTO_DIR, d))]
        if hasattr(self, 'folder_spinner'):
            self.folder_spinner.values = folders
            if self.cfg.get('selected_folder') not in folders:
                self.folder_spinner.text = 'Base'
                
        current_photo = self.photos[self.photo_index] if self.photos else None
        target_dir = self._get_active_dir()
        
        new_photos = self._get_photos_in_dir(target_dir)
        
        if not new_photos and target_dir != PHOTO_DIR:
            target_dir = PHOTO_DIR
            new_photos = self._get_photos_in_dir(target_dir)
            
        if self.cfg.get('playback_mode') == 'sorted':
            new_photos.sort(key=natural_sort_key)
        else:
            old_set = set(self.photos)
            new_set = set(new_photos)
            added = list(new_set - old_set)
            random.shuffle(added)
            new_photos = [p for p in self.photos if p in new_set] + added

        self.photos = new_photos
        
        if self.photos:
            if current_photo in self.photos:
                self.photo_index = self.photos.index(current_photo)
            else:
                self.photo_index = max(0, min(self.photo_index, len(self.photos) - 1))
                if self._state == 'IDLE':
                    self._next_slide(0)
                
        if manual:
            Popup(title="Sync Status", content=Label(text="Drive Sync Complete!"), size_hint=(0.4, 0.2)).open()

    def _check_for_updates(self, manual=False):
        threading.Thread(target=self._fetch_github_release, args=(manual,), daemon=True).start()

    def _fetch_github_release(self, manual):
        Logger.info("OTA: Checking GitHub for updates...")
        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                latest_version = data.get('tag_name', '').replace('v', '')
                if latest_version and latest_version != APP_VERSION:
                    Logger.info(f"OTA: Update found v{latest_version}")
                    apk_url = next((asset['browser_download_url'] for asset in data.get('assets', []) if asset['name'].endswith('.apk')), None)
                    if apk_url:
                        self._prompt_update(latest_version, apk_url)
                else:
                    Logger.info("OTA: App is up to date.")
                    if manual:
                        self._show_info_popup("OTA Status", "App is up to date.")
            else:
                Logger.warning(f"OTA: Check Failed - HTTP {r.status_code}")
                if manual:
                    self._show_info_popup("OTA Error", f"Server returned status {r.status_code}")
        except Exception as e:
            Logger.error(f"OTA: Update Check Error - {e}")
            if manual:
                self._show_info_popup("OTA Error", "Network error while checking.")

    @mainthread
    def _show_info_popup(self, title, text):
        Popup(title=title, content=Label(text=text), size_hint=(0.5, 0.3)).open()

    @mainthread
    def _prompt_update(self, version, url):
        content = GridLayout(cols=1, spacing=10)
        content.add_widget(Label(text=f"Version {version} is available!"))
        btn = Button(text="Download Update", size_hint_y=None, height=50)
        btn.bind(on_release=lambda x: webbrowser.open(url))
        content.add_widget(btn)
        Popup(title="Update Available", content=content, size_hint=(0.5, 0.3)).open()

    def _open_settings(self, instance):
        content = GridLayout(cols=2, spacing=10, size_hint_y=None, padding=[10, 40, 10, 80])
        content.bind(minimum_height=content.setter('height'))

        schema = [
            ('playback_mode', 'Playback Mode', 'toggle', ('sorted', 'random')),
            ('show_console', 'Show Console Overlay', 'bool', None),
            ('nav_mode', 'Navigation Mode', 'toggle', ('swipe', 'tap')),
            ('time_mode', 'Time/Loc Source', 'toggle', ('auto', 'manual')),
            ('fast_manual', 'Fast Manual Swipe', 'bool', None),
            ('format_24h', '24 Hour Time', 'bool', None),
            ('units', 'Units', 'toggle', ('imperial', 'metric')),
            ('slide_interval', 'Slide Interval (s)', 'number', None),
            ('fade_time', 'Fade Duration (s)', 'number', None),
            ('brightness', 'Brightness (0-1)', 'number', None),
            ('ui_opacity', 'UI Opacity (0-1)', 'number', None),
            ('sync_interval', 'Sync Interval (s)', 'number', None),
            ('weather_interval', 'Weather Int (s)', 'number', None),
            ('city', 'Manual City', 'text', None),
            ('region', 'Manual Region/State', 'text', None),
            ('tz_offset', 'Manual TZ Offset', 'text', None),
            ('weather_fmt', 'Weather Format String', 'text', None),
            ('text_color', 'Text Color (Hex)', 'text', None),
            ('stroke_color', 'Stroke Color (Hex)', 'text', None),
            ('api_key', 'OpenWeather API Key', 'text', None),
            ('folder_id', 'Drive Folder ID', 'text', None)
        ]

        self.ui_refs = {}

        content.add_widget(Label(text="Drive Sub-Folder", size_hint_y=None, height=40))
        folder_names = ['Base'] + [d for d in os.listdir(PHOTO_DIR) if os.path.isdir(os.path.join(PHOTO_DIR, d))]
        current_sel = self.cfg.get('selected_folder', 'Base')
        if current_sel not in folder_names: current_sel = 'Base'
        self.folder_spinner = Spinner(text=current_sel, values=folder_names, size_hint_y=None, height=40)
        content.add_widget(self.folder_spinner)

        for key, label, w_type, opts in schema:
            content.add_widget(Label(text=label, size_hint_y=None, height=40))
            if w_type == 'bool':
                btn = ToggleButton(text=str(self.cfg[key]), state='down' if self.cfg[key] else 'normal', size_hint_y=None, height=40)
                btn.bind(state=lambda b, val: setattr(b, 'text', str(val == 'down')))
                self.ui_refs[key] = btn
            elif w_type == 'toggle':
                btn = ToggleButton(text=self.cfg[key], state='down', size_hint_y=None, height=40)
                btn.opts = opts
                def toggle_opt(b):
                    b.text = b.opts[0] if b.text == b.opts[1] else b.opts[1]
                btn.bind(on_release=toggle_opt)
                self.ui_refs[key] = btn
            else:
                inp = TextInput(text=str(self.cfg[key]), multiline=False, size_hint_y=None, height=40)
                self.ui_refs[key] = inp
            content.add_widget(self.ui_refs[key])

        btn_grid = GridLayout(cols=3, spacing=5, size_hint_y=None, height=50)
        
        sync_btn = Button(text="Force Sync")
        sync_btn.bind(on_release=lambda x: threading.Thread(target=self._run_sync_pass, args=(True,), daemon=True).start())
        btn_grid.add_widget(sync_btn)

        update_btn = Button(text="Check OTA")
        update_btn.bind(on_release=lambda x: self._check_for_updates(manual=True))
        btn_grid.add_widget(update_btn)

        save_btn = Button(text="Save & Close")
        btn_grid.add_widget(save_btn)
        
        content.add_widget(Label(text="Actions", size_hint_y=None, height=50))
        content.add_widget(btn_grid)

        from kivy.uix.scrollview import ScrollView
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(content)

        self.popup = Popup(title=f"Settings (v{APP_VERSION})", content=scroll, size_hint=(0.85, 0.85))
        save_btn.bind(on_release=self._save_settings_ui)
        self.popup.open()

    def _save_settings_ui(self, instance):
        old_folder = self.cfg.get('selected_folder')
        old_playback = self.cfg.get('playback_mode')
        self.cfg['selected_folder'] = self.folder_spinner.text
        
        for key, widget in self.ui_refs.items():
            val = widget.text
            if isinstance(widget, ToggleButton) and val in ('True', 'False'):
                self.cfg[key] = (val == 'True')
            else:
                try:
                    self.cfg[key] = float(val) if '.' in val and key != 'text_color' else int(val)
                except ValueError:
                    self.cfg[key] = val
                    
        self._save_cfg()
        self._apply_ui_styles()
        self._trigger_weather()
        
        self.slide_event.cancel()
        self.weather_event.cancel()
        self.slide_event = Clock.schedule_interval(self._auto_slide, self.cfg['slide_interval'])
        self.weather_event = Clock.schedule_interval(self._trigger_weather, self.cfg['weather_interval'])
        
        if old_folder != self.cfg['selected_folder'] or old_playback != self.cfg['playback_mode']:
            self._current_dir = None
            self._next_slide(1, manual=True)
            
        self.popup.dismiss()

if __name__ == '__main__':
    PhotoFrameApp().run()