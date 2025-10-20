""" from django.utils.deprecation import MiddlewareMixin

class UserPreferencesMiddleware(MiddlewareMixin):
    def process_template_response(self, request, response):
        # Skip if response doesn't support context
        if not hasattr(response, 'context_data'):
            return response

        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            settings = getattr(user, "settings", None)  # Assuming OneToOne relation
            if settings:
                response.context_data["user_theme"] = settings.theme
                response.context_data["user_currency"] = settings.currency
                response.context_data["user_language"] = settings.language
        else:
            # Defaults for anonymous users
            response.context_data["user_theme"] = "dark"
            response.context_data["user_currency"] = "₹"
            response.context_data["user_language"] = "en"

        return response
 """