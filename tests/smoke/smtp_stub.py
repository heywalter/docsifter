"""A loopback SMTP server, for exercising the real smtplib path.

The rest of the email tests replace ``_send_email_with_retry`` and check the
message that would have been sent. That leaves the SMTP conversation itself --
the part that talks to a real server, and the part nobody had run before
release -- untested. This stub speaks enough of RFC 5321 for smtplib to
complete a session, so a test can assert on what actually went over the wire.

No TLS: a test configures ``email_use_tls=False`` and a port other than 465.
"""

import base64
import socket
import threading


class FakeSMTPServer:
    """An SMTP server on a loopback port that records what it receives."""

    def __init__(self, reject_auth: bool = False):
        self.reject_auth = reject_auth
        self.messages = []
        self.credentials = []
        # One connection per send attempt, which is what distinguishes the
        # service retrying from smtplib negotiating an AUTH mechanism.
        self.sessions = 0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(5)
        self.port = self._socket.getsockname()[1]
        self._stopped = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._stopped:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(connection,), daemon=True).start()

    def _session(self, connection):
        self.sessions += 1
        stream = connection.makefile("rb")

        def reply(line):
            connection.sendall(line.encode() + b"\r\n")

        reply("220 stub.localhost ESMTP")
        envelope = self._new_envelope()
        while True:
            raw = stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").strip()
            command = line.upper()

            if command.startswith(("EHLO", "HELO")):
                connection.sendall(b"250-stub.localhost\r\n250-AUTH PLAIN LOGIN\r\n250 OK\r\n")
            elif command.startswith("AUTH LOGIN"):
                reply("334 VXNlcm5hbWU6")
                username = base64.b64decode(stream.readline().strip()).decode()
                reply("334 UGFzc3dvcmQ6")
                password = base64.b64decode(stream.readline().strip()).decode()
                self.credentials.append((username, password))
                reply(
                    "535 5.7.8 Authentication credentials invalid"
                    if self.reject_auth
                    else "235 2.7.0 Authentication successful"
                )
            elif command.startswith("AUTH PLAIN"):
                parts = line.split(" ")
                blob = parts[2] if len(parts) > 2 else stream.readline().strip()
                decoded = base64.b64decode(blob).decode().split("\x00")
                self.credentials.append((decoded[1], decoded[2]))
                reply(
                    "535 5.7.8 Authentication credentials invalid"
                    if self.reject_auth
                    else "235 2.7.0 Authentication successful"
                )
            elif command.startswith("MAIL FROM"):
                envelope["mail_from"] = line
                reply("250 OK")
            elif command.startswith("RCPT TO"):
                envelope["rcpt_to"].append(line)
                reply("250 OK")
            elif command == "DATA":
                reply("354 End data with <CR><LF>.<CR><LF>")
                chunks = []
                while True:
                    data_line = stream.readline()
                    if data_line in (b".\r\n", b".\n", b""):
                        break
                    chunks.append(data_line)
                envelope["data"] = b"".join(chunks).decode("utf-8", "replace")
                self.messages.append(envelope)
                envelope = self._new_envelope()
                reply("250 OK queued")
            elif command == "QUIT":
                reply("221 Bye")
                break
            else:
                reply("250 OK")
        connection.close()

    @staticmethod
    def _new_envelope():
        return {"mail_from": None, "rcpt_to": [], "data": None}

    def stop(self):
        self._stopped = True
        try:
            self._socket.close()
        except OSError:
            pass
