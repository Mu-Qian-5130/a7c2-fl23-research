"""Record either reported charge or explicit adequate-power confirmation."""


def require_power(battery=None, *, confirmed=False):
    if confirmed is True:
        return {'source': 'user-confirmed-adequate-power', 'battery_percent': None,
                'usb_battery_measured': False}
    if type(battery) is int and 50 <= battery <= 100:
        return {'source': 'user-reported-percentage', 'battery_percent': battery,
                'usb_battery_measured': False}
    raise ValueError('Confirm adequate continuous power, or report a battery percentage of 50..100')
