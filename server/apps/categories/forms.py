def category_admin_form_factory():
    """Factory function to create CategoryAdminForm with i18n support."""

    from server.apps.translations.forms import required_i18n_fields_form_factory

    # Get the base form with i18n support
    base_form = required_i18n_fields_form_factory("name")

    # Create a new form that inherits from the base form and adds compact color widgets
    class CategoryAdminForm(base_form):
        """Custom form for Category admin with compact color widgets."""

        class Meta:
            fields = "__all__"

    return CategoryAdminForm
