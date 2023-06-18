import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ks_includes.KlippyGcodes import KlippyGcodes
from ks_includes.screen_panel import ScreenPanel

import logging


def create_panel(*args):
    return ZCalibratePanel(*args)


class ZCalibratePanel(ScreenPanel):
    widgets = {}
    distances = ['.01', '.05', '.1', '.5', '1', '5']
    distance = distances[-2]

    def __init__(self, screen, title):
        super().__init__(screen, title)
        self.z_offset = None
        self.wait_for_continue = False
        if "axis_twist_compensation" in self._printer.get_config_section_list():
            twist_compensation = self._printer.get_config_section(
                "axis_twist_compensation"
            )
            if ('wait_for_continue' in twist_compensation
                    and twist_compensation['wait_for_continue'] == 'true'):
                self.wait_for_continue = True
        self.probe = self._printer.get_probe()
        if self.probe:
            self.z_offset = float(self.probe['z_offset'])
        logging.info(f"Z offset: {self.z_offset}")
        self.widgets['zposition'] = Gtk.Label("Z: ?")

        pos = self._gtk.HomogeneousGrid()
        pos.attach(self.widgets['zposition'], 0, 1, 2, 1)
        if self.z_offset is not None:
            self.widgets['zoffset'] = Gtk.Label("?")
            pos.attach(Gtk.Label(_("Probe Offset") + ": "), 0, 2, 2, 1)
            pos.attach(Gtk.Label(_("Saved")), 0, 3, 1, 1)
            pos.attach(Gtk.Label(_("New")), 1, 3, 1, 1)
            pos.attach(Gtk.Label(f"{self.z_offset:.3f}"), 0, 4, 1, 1)
            pos.attach(self.widgets['zoffset'], 1, 4, 1, 1)
        self.buttons = {
            'zpos': self._gtk.Button('z-farther', _("Raise Nozzle"), 'color4'),
            'zneg': self._gtk.Button('z-closer', _("Lower Nozzle"), 'color1'),
            'start': self._gtk.Button('resume', _("Start"), 'color3'),
            'complete': self._gtk.Button('complete', _('Accept'), 'color3'),
            'cancel': self._gtk.Button('cancel', _('Abort'), 'color2'),
        }
        self.buttons['zpos'].connect("clicked", self.move, "+")
        self.buttons['zneg'].connect("clicked", self.move, "-")
        self.buttons['complete'].connect("clicked", self.accept)
        self.buttons['cancel'].connect("clicked", self.abort)

        self.functions = []
        self.functions.append("twist_compensation")

        logging.info(f"Available functions for calibration: {self.functions}")

        self.start_handler = self.buttons['start'].connect("clicked",
                                                           self.
                                                           start_calibration)
        self.continue_handler = None

        distgrid = Gtk.Grid()
        for j, i in enumerate(self.distances):
            self.widgets[i] = self._gtk.Button(label=i)
            self.widgets[i].set_direction(Gtk.TextDirection.LTR)
            self.widgets[i].connect("clicked", self.change_distance, i)
            ctx = self.widgets[i].get_style_context()
            if (self._screen.lang_ltr and j == 0) or (not self._screen.lang_ltr and j == len(self.distances) - 1):
                ctx.add_class("distbutton_top")
            elif (not self._screen.lang_ltr and j == 0) or (self._screen.lang_ltr and j == len(self.distances) - 1):
                ctx.add_class("distbutton_bottom")
            else:
                ctx.add_class("distbutton")
            if i == self.distance:
                ctx.add_class("distbutton_active")
            distgrid.attach(self.widgets[i], j, 0, 1, 1)

        self.widgets['move_dist'] = Gtk.Label(_("Move Distance (mm)"))
        distances = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        distances.pack_start(self.widgets['move_dist'], True, True, 0)
        distances.pack_start(distgrid, True, True, 0)

        self.grid = Gtk.Grid()
        self.grid.set_column_homogeneous(True)
        if self._screen.vertical_mode:
            self.grid.attach(self.buttons['zpos'], 0, 1, 1, 1)
            self.grid.attach(self.buttons['zneg'], 0, 2, 1, 1)
            self.grid.attach(self.buttons['start'], 0, 0, 1, 1)
            self.grid.attach(pos, 1, 0, 1, 1)
            self.grid.attach(self.buttons['complete'], 1, 1, 1, 1)
            self.grid.attach(self.buttons['cancel'], 1, 2, 1, 1)
            self.grid.attach(distances, 0, 3, 2, 1)
        else:
            self.grid.attach(self.buttons['zpos'], 0, 0, 1, 1)
            self.grid.attach(self.buttons['zneg'], 0, 1, 1, 1)
            self.grid.attach(self.buttons['start'], 1, 0, 1, 1)
            self.grid.attach(pos, 1, 1, 1, 1)
            self.grid.attach(self.buttons['complete'], 2, 0, 1, 1)
            self.grid.attach(self.buttons['cancel'], 2, 1, 1, 1)
            self.grid.attach(distances, 0, 2, 3, 1)
        self.content.add(self.grid)

    def start_calibration(self, widget):
        if self.wait_for_continue:
            self.buttons['start'].set_label('Continue')
            self.buttons['start'].disconnect(self.start_handler)
            self.continue_handler = self.buttons['start'].connect("clicked",
                                                                  self
                                                                  .continue_
                                                                  )
        self.disable_start_button()
        self._screen._ws.klippy.gcode_script(
            "AXIS_TWIST_COMPENSATION_CALIBRATE"
        )

    def process_busy(self, busy):
        for button in self.buttons:
            if button != 'start':
                self.buttons[button].set_sensitive(not busy)

    def process_update(self, action, data):
        if action == "notify_busy":
            self.process_busy(data)
        elif action == "notify_status_update":
            if self._printer.get_stat("toolhead", "homed_axes") != "xyz":
                self.widgets['zposition'].set_text("Z: ?")
            elif "gcode_move" in data and "gcode_position" in data['gcode_move']:
                self.update_position(data['gcode_move']['gcode_position'])
        elif action == "notify_gcode_response":
            data = data.lower()
            if "unknown" in data:
                self.buttons_not_calibrating()
                logging.info(data)
            elif "save_config" in data:
                self.buttons_not_calibrating()
                self.reset_start_button()
            elif "out of range" in data:
                self._screen.show_popup_message(data)
                self.buttons_not_calibrating()
                logging.info(data)
            elif "continue" in data:
                self.buttons_not_calibrating()
            elif "probe cancelled" in data and "calibration aborted" in data:
                self._screen.show_popup_message(_("Failed, adjust position first"))
                self.buttons_not_calibrating()
                self.reset_start_button()
                logging.info(data)
            elif "use testz" in data or "use abort" in data or "z position" in data:
                self.buttons_calibrating()
        return

    def update_position(self, position):
        self.widgets['zposition'].set_text(f"Z: {position[2]:.3f}")
        if self.z_offset is not None:
            self.widgets['zoffset'].set_text(f"{position[2] - self.z_offset:.3f}")

    def change_distance(self, widget, distance):
        logging.info(f"### Distance {distance}")
        self.widgets[f"{self.distance}"].get_style_context().remove_class("distbutton_active")
        self.widgets[f"{distance}"].get_style_context().add_class("distbutton_active")
        self.distance = distance

    def move(self, widget, direction):
        self._screen._ws.klippy.gcode_script(KlippyGcodes.testz_move(f"{direction}{self.distance}"))

    def continue_(self, widget):
        logging.info("Continuing calibration")
        self.disable_start_button()
        self._screen._ws.klippy.gcode_script(KlippyGcodes.CONTINUE)

    def abort(self, widget):
        logging.info("Aborting calibration")
        self._screen._ws.klippy.gcode_script(KlippyGcodes.ABORT)
        self.buttons_not_calibrating()
        self.reset_start_button()
        self._screen._menu_go_back()

    def accept(self, widget):
        logging.info("Accepting Z position")
        self._screen._ws.klippy.gcode_script(KlippyGcodes.ACCEPT)

    def buttons_calibrating(self):
        self.buttons['start'].set_sensitive(False)
        self.buttons['start'].get_style_context().remove_class('color3')

        self.buttons['zpos'].set_sensitive(True)
        self.buttons['zpos'].get_style_context().add_class('color4')
        self.buttons['zneg'].set_sensitive(True)
        self.buttons['zneg'].get_style_context().add_class('color1')
        self.buttons['complete'].set_sensitive(True)
        self.buttons['complete'].get_style_context().add_class('color3')
        self.buttons['cancel'].set_sensitive(True)
        self.buttons['cancel'].get_style_context().add_class('color2')

    def buttons_not_calibrating(self):
        self.buttons['start'].get_style_context().add_class('color3')
        self.buttons['start'].set_sensitive(True)

        self.buttons['zpos'].set_sensitive(False)
        self.buttons['zpos'].get_style_context().remove_class('color4')
        self.buttons['zneg'].set_sensitive(False)
        self.buttons['zneg'].get_style_context().remove_class('color1')
        self.buttons['complete'].set_sensitive(False)
        self.buttons['complete'].get_style_context().remove_class('color3')
        self.buttons['cancel'].set_sensitive(False)
        self.buttons['cancel'].get_style_context().remove_class('color2')

    def reset_start_button(self):
        self.buttons['start'].set_label('Start')
        self.buttons['start'].disconnect(self.continue_handler)
        self.start_handler = self.buttons['start'].connect("clicked",
                                                           self.
                                                           start_calibration,
                                                           self.functions[
                                                               0])
        
    def disable_start_button(self):
        self.buttons['start'].set_sensitive(False)
        self.buttons['start'].get_style_context().remove_class('color3')

    def activate(self):
        # This is only here because klipper doesn't provide a method to detect if it's calibrating
        self._screen._ws.klippy.gcode_script(KlippyGcodes.testz_move("+0.001"))
