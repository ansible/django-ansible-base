class InvalidService(Exception):
    def __init__(self, service):
        super().__init__(f"This authentication class requires {service}.")
