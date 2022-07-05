# DiscordBackupBot

🚀 A Discord bot to automatically back up your server messages data

[![Supported Python versions](https://img.shields.io/badge/Python-%3E=3.6-blue.svg?logo=python)](https://www.python.org/downloads/) [![PEP8](https://img.shields.io/badge/Code%20style-PEP%208-orange.svg?logo=python)](https://www.python.org/dev/peps/pep-0008/) [![Discord.py](https://img.shields.io/badge/Discord.py->=2.0.0a-yellow.svg?logo=python)](https://www.python.org/dev/peps/pep-0008/)

[![Discord](https://img.shields.io/badge/Invite%20To%20Your%20Server-%237289DA.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/api/oauth2/authorize?client_id=993789756955705375&permissions=117760&scope=bot)


## Requirements
- 🐍 [python>=3.6](https://www.python.org/downloads/)


## ⬇️ Installation

```sh
git clone https://github.com/Alyetama/auto-discord-server-backup.git
cd auto-discord-server-backup
pip install -r requirements.txt && rm -rf src
```


## ⌨️ Usage

- Rename `.env.example` to `.env`, then edit it with your favorite text editor to add your bot token.
- Then, run:

```sh
python bot.py
```

## 🐳 Docker

```sh
docker run -d -e BOT_TOKEN="xxxxxxxxxxxxx" alyetama/discord-backup-bot:latest
```
