from django.db import models
from django.utils.timezone import now


class MonitorFields(models.DateTimeField):
    """
    A DateTimeField that monitors other fields on the same model and
    sets itself to the current date/time whenever the monitored field
    changes.

    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("default", None)
        kwargs.setdefault("blank", True)
        kwargs.setdefault("null", True)
        monitors = kwargs.pop("monitors", None)
        if not monitors:
            raise TypeError(
                '%s requires a "monitors" argument' % self.__class__.__name__
            )
        self.monitors = monitors
        super().__init__(*args, **kwargs)

    def contribute_to_class(self, cls, name):
        self.monitors_attname = []
        for m in self.monitors:
            self.monitors_attname.append(f"_monitor_{m}_{name}")
        models.signals.post_init.connect(self._save_initial, sender=cls)
        super().contribute_to_class(cls, name)

    def get_monitored_value(self, monitor, instance):
        return getattr(instance, monitor)

    def _save_initial(self, sender, instance, **kwargs):
        for i, m in enumerate(self.monitors):
            attrname = self.monitors_attname[i]
            if m in instance.get_deferred_fields():
                # Fix related to issue #241 to avoid recursive error on double monitors fields
                continue
            setattr(
                instance,
                attrname,
                self.get_monitored_value(monitor=m, instance=instance),
            )

    def pre_save(self, model_instance, add):
        value = now()
        currents = []
        update = False
        for i, m in enumerate(self.monitors):
            attrname = self.monitors_attname[i]
            previous = getattr(model_instance, attrname, None)
            current = self.get_monitored_value(monitor=m, instance=model_instance)
            if previous != current:
                update = True
            currents.append(current)

        if not any(currents):
            value = None
            update = True
        if update:
            setattr(model_instance, self.attname, value)
            self._save_initial(model_instance.__class__, model_instance)
        return super().pre_save(model_instance, add)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["monitors"] = self.monitors
        return name, path, args, kwargs
