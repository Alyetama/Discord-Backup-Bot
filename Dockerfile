FROM python:3.8.13-slim

RUN apt update && \
	apt install git -y && \
	apt clean && \
	rm -rf /var/lib/apt/lists/*

COPY bot.py requirements.txt app/
RUN pip install -r app/requirements.txt && \
	rm -rf ~/.cache src

CMD ["python", "app/bot.py"]
