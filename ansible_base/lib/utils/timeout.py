import signal


class Timeout:
    """
    Timeout class using an alarm signal
    Basic usage:
        try:
            with Timeout(seconds):
               # Do something
        except Timeout.Timeout:
            print("Timed out trying to do the things")


    Borrowed from https://stackoverflow.com/questions/22537335/try-except-in-python-for-given-amount-of-time
    """

    class TimeoutException(Exception):
        pass

    def __init__(self, sec):
        self.sec = sec

    def __enter__(self):
        signal.signal(signal.SIGALRM, self.raise_timeout)
        signal.alarm(self.sec)

    def __exit__(self, *args):
        signal.alarm(0)  # disable alarm

    def raise_timeout(self, *args):
        raise Timeout.TimeoutException()
