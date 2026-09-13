# EZEyes
It's just two lines...

Reading assistant for wayland desktops with layer-shell. It has two lines with adjustable distances, 
thickness, colors and opacity for making reading easier.

## Requirements

- A Wayland desktop that supports layer-shell, such as KDE Plasma, Hyprland or Sway. GNOME on Wayland and X11 sessions aren't supported.
- Fedora, if you want the install script to set up everything for you. On other distros, first install your distro's versions of these packages: `python3`, `python3-gobject`, `python3-cairo`, `gtk3`, `gtk-layer-shell` and `libayatana-appindicator-gtk3`.

## Installation

```sh
git clone https://github.com/Gap-Shot/EZEyes.git
cd EZEyes
./install.sh
```

If any of the packages above are missing, the script installs them with `dnf` and asks for your password. The app itself is installed for your user only, under `~/.local`, and shows up in your app menu as **EasyEyes**.

Start it from the app menu or by running `easyeyes`. The first time it starts, your desktop asks you to approve two hotkeys: Alt+F8 and Alt+F9. If you want it to start when you log in, turn on **Start at login** in the settings.

### Updating

```sh
cd EZEyes
git pull
./install.sh
```

Then quit EasyEyes from its tray icon and start it again.

### Uninstalling

```sh
./install.sh --uninstall
```

This removes the app, its menu entry and its login entry. Your settings stay in `~/.config/easyeyes`; delete that folder if you don't want to keep them. KDE also keeps the hotkeys in its shortcut settings, and you can remove them there.

## Using it

| To | Do this |
| --- | --- |
| Show or hide the ruler | Press Alt+F8 |
| Move the ruler | Press Alt+F9 to turn on Move mode |
| Open the settings | Middle-click the tray icon, choose Settings from its menu, or run `easyeyes` |

While Move mode is on, EasyEyes takes over the keyboard and mouse:

- Tap Up or Down to move the ruler one line of text. The **Text line spacing** setting sets how far that is.
- Hold Up or Down to glide the ruler slowly.
- Click or drag anywhere, on any monitor, to put the ruler there.
- Press Esc, Enter or Alt+F9 when you're done.

KDE may put the tray icon under the **^** arrow in the system tray.

Your desktop owns the hotkeys. To change them, click **Change…** in the settings. On Sway or Hyprland, bind the keys in your config instead:

```
# Sway
bindsym Mod1+F8 exec ~/.local/bin/easyeyes toggle
bindsym Mod1+F9 exec ~/.local/bin/easyeyes move

# Hyprland
bind = ALT, F8, exec, ~/.local/bin/easyeyes toggle
bind = ALT, F9, exec, ~/.local/bin/easyeyes move
```
