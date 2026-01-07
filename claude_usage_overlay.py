import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import requests
from datetime import datetime
from pathlib import Path
import threading
import time
import asyncio
from webview import create_window, start
import webview.menu as wm

class ClaudeUsageBar:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Claude Usage")
        self.root.attributes('-topmost', True)
        self.root.overrideredirect(True)
        
        # Paths
        self.app_data_dir = Path(os.getenv('APPDATA')) / 'ClaudeUsageBar'
        self.app_data_dir.mkdir(exist_ok=True)
        self.config_file = self.app_data_dir / 'config.json'
        
        # Load config
        self.config = self.load_config()
        
        # State
        self.dragging = False
        self.drag_x = 0
        self.drag_y = 0
        self.usage_data = None
        self.polling_active = True
        self.webview_window = None
        self.session_key_found = False
        
        # Setup UI
        self.setup_ui()
        self.position_window()
        
        # Check if we have auth token
        if not self.config.get('session_key'):
            self.root.after(500, self.show_login_flow)
        else:
            self.start_polling()
        
    def load_config(self):
        default = {
            'position': {'x': 20, 'y': 80},
            'opacity': 0.9,
            'session_key': None,
            'poll_interval': 60
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    return {**default, **loaded}
            except:
                pass
        
        return default
    
    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def show_login_flow(self):
        """Show login dialog and launch browser"""
        login_dlg = tk.Toplevel(self.root)
        login_dlg.title("Login Required")
        login_dlg.geometry("450x200")
        login_dlg.configure(bg='#1a1a1a')
        login_dlg.attributes('-topmost', True)
        login_dlg.protocol("WM_DELETE_WINDOW", lambda: None)
        
        # Center
        login_dlg.update_idletasks()
        x = (login_dlg.winfo_screenwidth() // 2) - 225
        y = (login_dlg.winfo_screenheight() // 2) - 100
        login_dlg.geometry(f'+{x}+{y}')
        
        tk.Label(
            login_dlg,
            text="🔐 Login to Claude",
            font=('Segoe UI', 16, 'bold'),
            fg='#CC785C',
            bg='#1a1a1a'
        ).pack(pady=(30, 15))
        
        status_label = tk.Label(
            login_dlg,
            text="Click 'Sign In' to open login window",
            font=('Segoe UI', 10),
            fg='#999999',
            bg='#1a1a1a'
        )
        status_label.pack(pady=10)
        
        def start_browser_login():
            btn.config(state='disabled', text="Opening...")
            status_label.config(text="Please log in to Claude in the new window...")
            login_dlg.update()
            
            # Launch browser in separate thread
            threading.Thread(
                target=self.launch_login_browser,
                args=(login_dlg, status_label),
                daemon=True
            ).start()
        
        btn = tk.Button(
            login_dlg,
            text="Sign In",
            command=start_browser_login,
            bg='#CC785C',
            fg='#ffffff',
            font=('Segoe UI', 11, 'bold'),
            relief='flat',
            cursor='hand2',
            padx=50,
            pady=12
        )
        btn.pack(pady=20)
    
    def launch_login_browser(self, parent_window, status_label):
        """Launch Edge WebView2 browser for login"""
        
        class API:
            def __init__(self, app):
                self.app = app
                self.checking = True
            
            def check_cookies(self):
                """Called from JavaScript to check cookies"""
                while self.checking and self.app.webview_window:
                    try:
                        # Evaluate JavaScript to get cookies
                        js_code = """
                        (function() {
                            var cookies = document.cookie.split(';');
                            for(var i = 0; i < cookies.length; i++) {
                                var cookie = cookies[i].trim();
                                if(cookie.startsWith('sessionKey=')) {
                                    return cookie.substring(11);
                                }
                            }
                            return null;
                        })();
                        """
                        
                        result = self.app.webview_window.evaluate_js(js_code)
                        
                        if result:
                            self.app.config['session_key'] = result
                            self.app.save_config()
                            self.app.session_key_found = True
                            self.checking = False
                            
                            # Close the browser window
                            self.app.webview_window.destroy()
                            
                            # Update parent UI
                            parent_window.after(0, lambda: [
                                status_label.config(text="✓ Login successful!", fg='#44ff44'),
                                parent_window.after(1000, parent_window.destroy)
                            ])
                            
                            # Start polling
                            self.app.root.after(0, self.app.start_polling)
                            return
                        
                        time.sleep(2)  # Check every 2 seconds
                    except:
                        time.sleep(2)
        
        api = API(self)
        
        # Create webview window
        self.webview_window = create_window(
            'Sign in to Claude',
            'https://claude.ai',
            width=1000,
            height=800,
            resizable=True,
            js_api=api
        )
        
        # Start cookie checking in background
        def start_checking():
            time.sleep(3)  # Wait for page to load
            api.check_cookies()
        
        threading.Thread(target=start_checking, daemon=True).start()
        
        # Start webview - this blocks until window closes
        try:
            start()
        except:
            pass
        
        # If we get here and no session key found
        if not self.session_key_found:
            parent_window.after(0, lambda: [
                status_label.config(text="Login cancelled. Please try again.", fg='#ff4444')
            ])
    
    def fetch_usage_data(self):
        """Fetch usage data from Claude API"""
        if not self.config.get('session_key'):
            return None
            
        try:
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': f'sessionKey={self.config["session_key"]}',
                'Origin': 'https://claude.ai',
                'Referer': 'https://claude.ai/'
            }
            
            # Get organizations
            response = requests.get(
                'https://claude.ai/api/organizations',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                orgs = response.json()
                if orgs and len(orgs) > 0:
                    org_id = orgs[0].get('uuid')
                    
                    # Get usage
                    usage_response = requests.get(
                        f'https://claude.ai/api/organizations/{org_id}/usage',
                        headers=headers,
                        timeout=10
                    )
                    
                    if usage_response.status_code == 200:
                        return usage_response.json()
            
            elif response.status_code == 401:
                self.root.after(0, self.handle_auth_error)
                return None
            
            return None
                
        except Exception as e:
            print(f"Error fetching usage: {e}")
            return None
    
    def handle_auth_error(self):
        """Handle authentication errors"""
        if messagebox.askyesno("Session Expired", 
                               "Your session has expired. Would you like to log in again?"):
            self.config['session_key'] = None
            self.save_config()
            self.show_login_flow()
    
    def polling_loop(self):
        """Background thread for polling API"""
        while self.polling_active:
            data = self.fetch_usage_data()
            if data:
                self.usage_data = data
                self.root.after(0, self.update_progress)
            
            time.sleep(self.config['poll_interval'])
    
    def start_polling(self):
        """Start background polling thread"""
        self.polling_active = True
        poll_thread = threading.Thread(target=self.polling_loop, daemon=True)
        poll_thread.start()
        
        # Initial fetch
        def initial_fetch():
            time.sleep(0.5)
            data = self.fetch_usage_data()
            if data:
                self.usage_data = data
                self.root.after(0, self.update_progress)
        
        threading.Thread(target=initial_fetch, daemon=True).start()
    
    def setup_ui(self):
        self.main_frame = tk.Frame(
            self.root,
            bg='#1a1a1a',
            relief='flat',
            bd=0
        )
        self.main_frame.pack(fill='both', expand=True, padx=1, pady=1)
        
        self.root.configure(bg='#1a1a1a')
        
        # Header
        self.header = tk.Frame(self.main_frame, bg='#2a2a2a', height=28)
        self.header.pack(fill='x', padx=6, pady=(6, 0))
        self.header.pack_propagate(False)
        
        self.title_label = tk.Label(
            self.header,
            text="Claude Usage",
            font=('Segoe UI', 9, 'bold'),
            fg='#CC785C',
            bg='#2a2a2a',
            cursor='hand2'
        )
        self.title_label.pack(side='left', padx=8, pady=4)
        
        # Dragging
        for widget in [self.header, self.title_label]:
            widget.bind('<Button-1>', self.start_drag)
            widget.bind('<B1-Motion>', self.on_drag)
            widget.bind('<ButtonRelease-1>', self.stop_drag)
        
        # Buttons
        btn_frame = tk.Frame(self.header, bg='#2a2a2a')
        btn_frame.pack(side='right')
        
        # Refresh
        self.refresh_btn = tk.Label(
            btn_frame,
            text="⟳",
            font=('Segoe UI', 11, 'bold'),
            fg='#888888',
            bg='#2a2a2a',
            cursor='hand2',
            padx=4
        )
        self.refresh_btn.pack(side='left', padx=2)
        self.refresh_btn.bind('<Button-1>', self.manual_refresh)
        self.refresh_btn.bind('<Enter>', lambda e: self.refresh_btn.config(fg='#CC785C'))
        self.refresh_btn.bind('<Leave>', lambda e: self.refresh_btn.config(fg='#888888'))
        
        # Settings
        self.settings_btn = tk.Label(
            btn_frame,
            text="⚙",
            font=('Segoe UI', 10),
            fg='#888888',
            bg='#2a2a2a',
            cursor='hand2',
            padx=4
        )
        self.settings_btn.pack(side='left', padx=2)
        self.settings_btn.bind('<Button-1>', self.show_settings)
        self.settings_btn.bind('<Enter>', lambda e: self.settings_btn.config(fg='#ffffff'))
        self.settings_btn.bind('<Leave>', lambda e: self.settings_btn.config(fg='#888888'))
        
        # Close
        self.close_btn = tk.Label(
            btn_frame,
            text="×",
            font=('Segoe UI', 13, 'bold'),
            fg='#888888',
            bg='#2a2a2a',
            cursor='hand2',
            padx=4
        )
        self.close_btn.pack(side='left', padx=2)
        self.close_btn.bind('<Button-1>', self.on_close)
        self.close_btn.bind('<Enter>', lambda e: self.close_btn.config(fg='#ff4444'))
        self.close_btn.bind('<Leave>', lambda e: self.close_btn.config(fg='#888888'))
        
        # Content
        content = tk.Frame(self.main_frame, bg='#1a1a1a')
        content.pack(fill='x', padx=8, pady=8)
        
        # Usage section
        tk.Label(
            content,
            text="Current Usage",
            font=('Segoe UI', 8, 'bold'),
            fg='#888888',
            bg='#1a1a1a',
            anchor='w'
        ).pack(fill='x', pady=(0, 2))
        
        self.usage_label = tk.Label(
            content,
            text="Loading...",
            font=('Segoe UI', 9),
            fg='#cccccc',
            bg='#1a1a1a',
            anchor='w'
        )
        self.usage_label.pack(fill='x', pady=(0, 2))
        
        # Progress bar
        progress_bg = tk.Frame(content, bg='#2a2a2a', height=12)
        progress_bg.pack(fill='x', pady=(0, 4))
        progress_bg.pack_propagate(False)
        
        self.progress_fill = tk.Frame(progress_bg, bg='#CC785C', height=12)
        self.progress_fill.place(x=0, y=0, relheight=1, width=0)
        
        self.reset_label = tk.Label(
            content,
            text="Next reset: --:--:--",
            font=('Segoe UI', 7),
            fg='#666666',
            bg='#1a1a1a',
            anchor='w'
        )
        self.reset_label.pack(fill='x')
        
        # Set opacity
        self.root.attributes('-alpha', self.config['opacity'])
        self.root.geometry('300x140')
    
    def start_drag(self, event):
        self.dragging = True
        self.drag_x = event.x_root - self.root.winfo_x()
        self.drag_y = event.y_root - self.root.winfo_y()
    
    def on_drag(self, event):
        if self.dragging:
            x = event.x_root - self.drag_x
            y = event.y_root - self.drag_y
            self.root.geometry(f'+{x}+{y}')
    
    def stop_drag(self, event):
        if self.dragging:
            self.dragging = False
            self.config['position']['x'] = self.root.winfo_x()
            self.config['position']['y'] = self.root.winfo_y()
            self.save_config()
    
    def position_window(self):
        self.root.update_idletasks()
        x = self.config['position']['x']
        y = self.config['position']['y']
        self.root.geometry(f'+{x}+{y}')
    
    def update_progress(self):
        """Update UI with latest usage data"""
        if not self.usage_data:
            return
        
        try:
            usage_pct = 0
            
            if isinstance(self.usage_data, dict):
                if 'usage_percentage' in self.usage_data:
                    usage_pct = self.usage_data['usage_percentage']
                elif 'usage_data' in self.usage_data and 'percentage' in self.usage_data['usage_data']:
                    usage_pct = self.usage_data['usage_data']['percentage']
                elif 'current' in self.usage_data and 'limit' in self.usage_data:
                    current = self.usage_data['current']
                    limit = self.usage_data['limit']
                    if limit > 0:
                        usage_pct = (current / limit) * 100
                elif 'usage' in self.usage_data:
                    usage = self.usage_data['usage']
                    if isinstance(usage, dict):
                        if 'percentage' in usage:
                            usage_pct = usage['percentage']
                        elif 'current' in usage and 'limit' in usage:
                            if usage['limit'] > 0:
                                usage_pct = (usage['current'] / usage['limit']) * 100
            
            self.usage_label.config(text=f"{usage_pct:.1f}% of limit used")
            
            # Update progress bar
            bar_width = int((usage_pct / 100) * 284)
            self.progress_fill.place(width=bar_width)
            
            # Color based on usage
            if usage_pct >= 90:
                self.progress_fill.config(bg='#ff4444')
            elif usage_pct >= 70:
                self.progress_fill.config(bg='#ffaa44')
            else:
                self.progress_fill.config(bg='#CC785C')
                
        except Exception as e:
            print(f"Error updating progress: {e}")
            self.usage_label.config(text="Connected")
        
        # Schedule next update
        self.root.after(1000, self.update_progress)
    
    def manual_refresh(self, event=None):
        """Manually trigger refresh"""
        def refresh():
            data = self.fetch_usage_data()
            if data:
                self.usage_data = data
                self.root.after(0, self.update_progress)
        
        threading.Thread(target=refresh, daemon=True).start()
    
    def show_settings(self, event=None):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")
        settings_win.geometry("350x250")
        settings_win.attributes('-topmost', True)
        settings_win.configure(bg='#1a1a1a')
        
        # Opacity
        tk.Label(
            settings_win,
            text="Opacity:",
            font=('Segoe UI', 9),
            fg='#cccccc',
            bg='#1a1a1a'
        ).pack(pady=(15, 5))
        
        opacity_var = tk.DoubleVar(value=self.config['opacity'])
        opacity_slider = ttk.Scale(
            settings_win,
            from_=0.3,
            to=1.0,
            variable=opacity_var,
            orient='horizontal',
            length=250
        )
        opacity_slider.pack()
        
        # Poll interval
        tk.Label(
            settings_win,
            text="Update Interval (seconds):",
            font=('Segoe UI', 9),
            fg='#cccccc',
            bg='#1a1a1a'
        ).pack(pady=(15, 5))
        
        interval_var = tk.IntVar(value=self.config['poll_interval'])
        interval_spinbox = tk.Spinbox(
            settings_win,
            from_=10,
            to=300,
            textvariable=interval_var,
            font=('Segoe UI', 10),
            bg='#2a2a2a',
            fg='#ffffff',
            width=10
        )
        interval_spinbox.pack()
        
        # Save
        def save_settings():
            self.config['opacity'] = opacity_var.get()
            self.config['poll_interval'] = interval_var.get()
            self.root.attributes('-alpha', self.config['opacity'])
            self.save_config()
            settings_win.destroy()
        
        tk.Button(
            settings_win,
            text="Save Settings",
            command=save_settings,
            bg='#CC785C',
            fg='#ffffff',
            relief='flat',
            font=('Segoe UI', 9, 'bold'),
            padx=20,
            pady=6
        ).pack(pady=20)
        
        # Logout
        def logout():
            if messagebox.askyesno("Logout", "Log out and clear session?", parent=settings_win):
                self.config['session_key'] = None
                self.save_config()
                settings_win.destroy()
                self.root.quit()
        
        tk.Button(
            settings_win,
            text="Logout",
            command=logout,
            bg='#2a2a2a',
            fg='#888888',
            relief='flat',
            font=('Segoe UI', 8)
        ).pack()
    
    def on_close(self, event=None):
        self.polling_active = False
        if self.webview_window:
            try:
                self.webview_window.destroy()
            except:
                pass
        self.root.quit()
    
    def run(self):
        self.root.mainloop()

if __name__ == '__main__':
    app = ClaudeUsageBar()
    app.run()