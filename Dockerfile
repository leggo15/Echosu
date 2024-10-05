FROM debian:12.5-slim

WORKDIR /echosu

RUN apt update
RUN apt install -y \
	python3 \
	python3-pip

# normally not a good idea, but we are in a container, so we dont need to worry about breaking anything:
RUN rm /usr/lib/python3.11/EXTERNALLY-MANAGED

# apt's cargo version is too old
RUN apt install curl -y
RUN curl https://sh.rustup.rs -sSf > install_rust.sh && sh install_rust.sh -y
RUN export PATH="$PATH:/root/.cargo/bin"
#RUN ln -s /root/.cargo/bin/cargo /bin
#RUN ln -s /root/.cargo/bin/rustc /bin

RUN --mount=type=bind,dst=./requirements.txt,src=./requirements.txt \
	pip3 install -r requirements.txt

#USER echosu

ENTRYPOINT [ "python3", "./manage.py", "runserver", "0.0.0.0:8080" ]
