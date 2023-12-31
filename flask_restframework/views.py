from flask import current_app, g
from flask import views
from . import exceptions


class APIView(views.MethodView):
    authentication_classes = []
    permission_classes = []
    throttle_handlers = []

    def dispatch_request(self, *args, **kwargs):
        try:
            self.initial()
        except Exception as exc:
            return self.handle_exception(exc)
        return super().dispatch_request(*args, **kwargs)

    def initial(self):
        self.perform_authentication()
        self.check_permissions()
        self.check_throttles()

    def get_authenticators(self):
        """
        Instantiates and returns the list of authenticators that this view can use.
        """
        global_auth_config = getattr(current_app, "AUTHENTICATION_CLASSES", [])
        self.authenticators = [auth() for auth in self.authentication_classes or global_auth_config]
        return self.authenticators

    def get_permissions(self):
        """
        Instantiates and returns the list of permissions that this view requires.
        """
        global_perm_config = getattr(current_app, "PERMISSION_CLASSES", [])
        return [permission() for permission in self.permission_classes or global_perm_config]

    def get_throttles(self):
        """
        Instantiates and returns the list of throttles that this view uses.
        """
        global_thro_config = getattr(current_app, "THROTTLE_HANDLERS", [])
        throttling_handlers = []
        for throttle in self.throttle_handlers or global_thro_config:
            throttle_class = throttle.get("class")
            throttle_rate = throttle.get("rate")
            throttling_handlers.append(throttle_class(throttle_rate))
        return throttling_handlers

    def perform_authentication(self):
        self.successful_authenticated = False
        for authenticator in self.get_authenticators():
            try:
                user_auth_tuple = authenticator.authenticate()
            except exceptions.APIException as exc:
                exc.auth_header = authenticator.authenticate_header()
                raise exc

            if user_auth_tuple is not None:
                self.successful_authenticated = True
                self.authenticator = authenticator
                return
        # not_authenticated
        g.current_user = None

    def check_permissions(self):
        """
        Check if the request should be permitted.
        Raises an appropriate exception if the request is not permitted.
        """
        for permission in self.get_permissions():
            if not permission.has_permission():
                self.permission_denied(
                    message=getattr(permission, "message", None), code=getattr(permission, "code", None)
                )

    def permission_denied(self, message=None, code=None):
        """
        If request is not permitted, determine what kind of exception to raise.
        """
        if self.authenticators and not self.successful_authenticated:
            exc = exceptions.NotAuthenticated()
            exc.auth_header = self.get_authenticate_header()
            raise exc
        raise exceptions.PermissionDenied(detail=message, code=code)

    def check_throttles(self):
        """
        Check if request should be throttled.
        Raises an appropriate exception if the request is throttled.
        """
        throttle_durations = []
        for throttle in self.get_throttles():
            if not throttle.allow_request():
                throttle_durations.append(throttle.wait())
        if throttle_durations:
            duration = max(throttle_durations, default=None)
            raise exceptions.Throttled(duration)

    def get_authenticate_header(self):
        """
        If a request is unauthenticated, determine the WWW-Authenticate
        header to use for 401 responses, if any.
        """
        if self.authenticators:
            return self.authenticators[0].authenticate_header()

    def handle_exception(self, exc):
        """
        Handle any exception that occurs, by returning an appropriate response,
        or re-raising the error.
        """
        exception_handler = getattr(current_app, "EXCEPTION_HANDLER", exceptions.exception_handler)
        return exception_handler(exc)
