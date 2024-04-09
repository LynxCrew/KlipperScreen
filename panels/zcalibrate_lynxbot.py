import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ks_includes.KlippyGcodes import KlippyGcodes
from ks_includes.screen_panel import ScreenPanel

import logging


class Panel(ScreenPanel):
    widgets = {}
    distances = ['.01', '.05', '.1', '.5', '1', '5']
    distance = distances[-2]

    def __init__(self, screen, title):
        super().__init__(screen, title)
        self.z_offset = None
        self.running = False
        self.calibrating = False
        self.twist_compensate_running = False
        self.probe = self._printer.get_probe()
        if self.probe:
            self.z_offset = float(self.probe['z_offset'])
        logging.info(f"Z offset: {self.z_offset}")
        self.widgets['zposition'] = Gtk.Label(label="Z: ?")

        pos = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        pos.attach(self.widgets['zposition'], 0, 1, 2, 1)
        if self.z_offset is not None:
            self.widgets['zoffset'] = Gtk.Label(label="?")
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
        self.cancel_handler = self.buttons['cancel'].connect("clicked", self.abort)

        self.start_handler = None
        self.continue_handler = None

        self.wait_for_continue = False
        if "axis_twist_compensation" in self._printer.get_config_section_list():
            twist_compensation = self._printer.get_config_section(
                "axis_twist_compensation"
            )
            if ('wait_for_continue' in twist_compensation
                    and twist_compensation['wait_for_continue'] == 'true'):
                self.wait_for_continue = True

        self.functions = []
        pobox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        if "Z_ENDSTOP_CALIBRATE" in self._printer.available_commands:
            self._add_button("Endstop", "endstop", pobox)
            self.functions.append("endstop")
        if "PROBE_CALIBRATE" in self._printer.available_commands:
            self._add_button("Probe", "probe", pobox)
            self.functions.append("probe")
        if "BED_MESH_CALIBRATE" in self._printer.available_commands and "probe" not in self.functions:
            # This is used to do a manual bed mesh if there is no probe
            self._add_button("Bed mesh", "mesh", pobox)
            self.functions.append("mesh")
        if "DELTA_CALIBRATE" in self._printer.available_commands:
            if "probe" in self.functions:
                self._add_button("Delta Automatic", "delta", pobox)
                self.functions.append("delta")
            # Since probes may not be accturate enough for deltas, always show the manual method
            self._add_button("Delta Manual", "delta_manual", pobox)
            self.functions.append("delta_manual")
        if "AXIS_TWIST_COMPENSATION_CALIBRATE" in self._printer.available_commands:
            self._add_button("Twist Compensation", "twist_compensation", pobox)
            self.functions.append("twist_compensation")

        logging.info(f"Available functions for calibration: {self.functions}")

        self.labels['popover'] = Gtk.Popover(position=Gtk.PositionType.BOTTOM)
        self.labels['popover'].add(pobox)

        self.reset_states()

        distgrid = Gtk.Grid()
        for j, i in enumerate(self.distances):
            self.widgets[i] = self._gtk.Button(label=i)
            self.widgets[i].set_direction(Gtk.TextDirection.LTR)
            self.widgets[i].connect("clicked", self.change_distance, i)
            ctx = self.widgets[i].get_style_context()
            ctx.add_class("horizontal_togglebuttons")
            if i == self.distance:
                ctx.add_class("horizontal_togglebuttons_active")
            distgrid.attach(self.widgets[i], j, 0, 1, 1)

        self.widgets['move_dist'] = Gtk.Label(_("Move Distance (mm)"))
        distances = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        distances.pack_start(self.widgets['move_dist'], True, True, 0)
        distances.pack_start(distgrid, True, True, 0)

        self.buttons_not_calibrating()

        grid = Gtk.Grid(column_homogeneous=True)
        if self._screen.vertical_mode:
            grid.attach(self.buttons['zpos'], 0, 1, 1, 1)
            grid.attach(self.buttons['zneg'], 0, 2, 1, 1)
            grid.attach(self.buttons['start'], 0, 0, 1, 1)
            grid.attach(pos, 1, 0, 1, 1)
            grid.attach(self.buttons['complete'], 1, 1, 1, 1)
            grid.attach(self.buttons['cancel'], 1, 2, 1, 1)
            grid.attach(distances, 0, 3, 2, 1)
        else:
            grid.attach(self.buttons['zpos'], 0, 0, 1, 1)
            grid.attach(self.buttons['zneg'], 0, 1, 1, 1)
            grid.attach(self.buttons['start'], 1, 0, 1, 1)
            grid.attach(pos, 1, 1, 1, 1)
            grid.attach(self.buttons['complete'], 2, 0, 1, 1)
            grid.attach(self.buttons['cancel'], 2, 1, 1, 1)
            grid.attach(distances, 0, 2, 3, 1)
        self.content.add(grid)

    def _add_button(self, label, method, pobox):
        popover_button = self._gtk.Button(label=label)
        popover_button.connect("clicked", self.start_calibration, method)
        pobox.pack_start(popover_button, True, True, 5)

    def on_popover_clicked(self, widget):
        if self.twist_compensate_running:
            self.continue_(None)
        else:
            self.labels['popover'].set_relative_to(widget)
            self.labels['popover'].show_all()

    def start_calibration(self, widget, method):
        self.labels['popover'].popdown()

        self.disable_start_button()

        self.running = True

        if method == "probe":
            self._screen._ws.klippy.gcode_script("CALIBRATE_PROBE")
        elif method == "mesh":
            self._screen._ws.klippy.gcode_script("LEVEL_AUTO")
        elif method == "delta":
            if self._printer.get_stat("toolhead", "homed_axes") != "xyz":
                self._screen._ws.klippy.gcode_script("G28")
            self._screen._ws.klippy.gcode_script("DELTA_CALIBRATE")
        elif method == "delta_manual":
            if self._printer.get_stat("toolhead", "homed_axes") != "xyz":
                self._screen._ws.klippy.gcode_script("G28")
            self._screen._ws.klippy.gcode_script("DELTA_CALIBRATE METHOD=manual")
        elif method == "endstop":
            self._screen._ws.klippy.gcode_script("CALIBRATE_Z_ENDSTOP")
        elif method == "twist_compensation":
            if self.wait_for_continue:
                if self.start_handler is not None:
                    self.buttons['start'].set_label('Continue')
                    self.buttons['start'].disconnect(self.start_handler)
                    self.start_handler = None
                if self.continue_handler is None:
                    self.continue_handler = self.buttons['start'].connect("clicked",
                                                                          self
                                                                          .continue_
                                                                          )
            self.twist_compensate_running = True
            self._screen._ws.klippy.gcode_script(
                "AXIS_TWIST_COMPENSATION_CALIBRATE"
            )

    def _move_to_position(self):
        x_position = y_position = None
        z_hop = speed = None
        # Get position from config
        if self.ks_printer_cfg is not None:
            x_position = self.ks_printer_cfg.getfloat("calibrate_x_position", None)
            y_position = self.ks_printer_cfg.getfloat("calibrate_y_position", None)
        elif 'z_calibrate_position' in self._config.get_config():
            # OLD global way, this should be deprecated
            x_position = self._config.get_config()['z_calibrate_position'].getfloat("calibrate_x_position", None)
            y_position = self._config.get_config()['z_calibrate_position'].getfloat("calibrate_y_position", None)

        if self.probe:
            if "sample_retract_dist" in self.probe:
                z_hop = self.probe['sample_retract_dist']
            if "speed" in self.probe:
                speed = self.probe['speed']

        # Use safe_z_home position
        if "safe_z_home" in self._printer.get_config_section_list():
            safe_z = self._printer.get_config_section("safe_z_home")
            safe_z_xy = safe_z['home_xy_position']
            safe_z_xy = [str(i.strip()) for i in safe_z_xy.split(',')]
            if x_position is None:
                x_position = float(safe_z_xy[0])
                logging.debug(f"Using safe_z x:{x_position}")
            if y_position is None:
                y_position = float(safe_z_xy[1])
                logging.debug(f"Using safe_z y:{y_position}")
            if 'z_hop' in safe_z:
                z_hop = safe_z['z_hop']
            if 'z_hop_speed' in safe_z:
                speed = safe_z['z_hop_speed']

        speed = 15 if speed is None else speed
        z_hop = 5 if z_hop is None else z_hop
        self._screen._ws.klippy.gcode_script(f"G91\nG0 Z{z_hop} F{float(speed) * 60}")
        if self._printer.get_stat("gcode_move", "absolute_coordinates"):
            self._screen._ws.klippy.gcode_script("G90")

        if x_position is not None and y_position is not None:
            logging.debug(f"Configured probing position X: {x_position} Y: {y_position}")
            self._screen._ws.klippy.gcode_script(f'G0 X{x_position} Y{y_position} F3000')
        elif "delta" in self._printer.get_config_section("printer")['kinematics']:
            logging.info("Detected delta kinematics calibrating at 0,0")
            self._screen._ws.klippy.gcode_script('G0 X0 Y0 F3000')
        else:
            self._calculate_position()

    def _calculate_position(self):
        logging.debug("Position not configured, probing the middle of the bed")
        try:
            xmax = float(self._printer.get_config_section("stepper_x")['position_max'])
            ymax = float(self._printer.get_config_section("stepper_y")['position_max'])
        except KeyError:
            logging.error("Couldn't get max position from stepper_x and stepper_y")
            return
        x_position = xmax / 2
        y_position = ymax / 2
        logging.info(f"Center position X:{x_position} Y:{y_position}")

        # Find probe offset
        x_offset = y_offset = None
        if self.probe:
            if "x_offset" in self.probe:
                x_offset = float(self.probe['x_offset'])
            if "y_offset" in self.probe:
                y_offset = float(self.probe['y_offset'])
        logging.info(f"Offset X:{x_offset} Y:{y_offset}")
        if x_offset is not None:
            x_position = x_position - x_offset
        if y_offset is not None:
            y_position = y_position - y_offset

        logging.info(f"Moving to X:{x_position} Y:{y_position}")
        self._screen._ws.klippy.gcode_script(f'G0 X{x_position} Y{y_position} F3000')

    def process_busy(self, busy):
        if self.running:
            for button in self.buttons:
                if button != 'start' and (button != 'cancel' or not self.twist_compensate_running):
                    self.buttons[button].set_sensitive(
                        (not busy) and self.calibrating)
        else:
            if not busy:
                self.buttons['start'].get_style_context().add_class('color3')
                self.buttons['start'].set_sensitive(True)
            else:
                self.buttons['start'].get_style_context().remove_class('color3')
                self.buttons['start'].set_sensitive(False)

    def process_update(self, action, data):
        if action == "notify_busy":
            self.process_busy(data)
        elif action == "notify_status_update":
            if self._printer.get_stat("toolhead", "homed_axes") != "xyz":
                self.widgets['zposition'].set_text("Z: ?")
            elif "gcode_move" in data and "gcode_position" in data['gcode_move']:
                self.update_position(data['gcode_move']['gcode_position'])
            if "manual_probe" in data or "axis_twist_compensation" in data:
                self.activate()
        elif action == "notify_gcode_response":
            data = data.lower()
            if ("probe cancelled" in data and "calibration aborted" in data):
                self.reset_states()
                self.buttons_not_calibrating()
                logging.info(data)
            elif "probe triggered prior to movement" in data:
                self.enable_cancel_button()
            elif "save_config" in data:
                self.reset_states()
                self.buttons_not_calibrating()
            elif "out of range" in data:
                self._screen.show_popup_message(data)
                self.reset_states()
                self.buttons_not_calibrating()
                logging.info(data)
            elif "continue" in data and "unknown command:" not in data:
                self.buttons_not_calibrating()
            elif ("fail" in data and "use testz" in data):
                self._screen.show_popup_message(_("Failed, adjust position first"))
                self.reset_states()
                self.buttons_not_calibrating()
                logging.info(data)
            elif "use testz" in data or "use abort" in data or "z position" in data:
                self.buttons_calibrating()
        return

    def update_position(self, position):
        self.widgets['zposition'].set_text(f"Z: {position[2]:.3f}")
        if self.z_offset is not None:
            self.widgets['zoffset'].set_text(f"{abs(position[2] - self.z_offset):.3f}")

    def change_distance(self, widget, distance):
        logging.info(f"### Distance {distance}")
        self.widgets[f"{self.distance}"].get_style_context().remove_class("horizontal_togglebuttons_active")
        self.widgets[f"{distance}"].get_style_context().add_class("horizontal_togglebuttons_active")
        self.distance = distance

    def move(self, widget, direction):
        self._screen._ws.klippy.gcode_script(f"TESTZ Z={direction}{self.distance}")

    def continue_(self, widget):
        logging.info("Continuing calibration")
        self.disable_start_button()
        self._screen._ws.klippy.gcode_script("CONTINUE")

    def abort(self, widget):
        logging.info("Aborting calibration")
        self._screen._ws.klippy.gcode_script("ABORT")
        self.reset_states()
        self.buttons_not_calibrating()
        self.disable_start_button()
        self._screen._menu_go_back()

    def accept(self, widget):
        logging.info("Accepting Z position")
        self._screen._ws.klippy.gcode_script("ACCEPT")

    def buttons_calibrating(self):
        self.calibrating = True
        self.buttons['start'].get_style_context().remove_class('color3')
        self.buttons['start'].set_sensitive(False)

        self.buttons['zpos'].set_sensitive(True)
        self.buttons['zpos'].get_style_context().add_class('color4')
        self.buttons['zneg'].set_sensitive(True)
        self.buttons['zneg'].get_style_context().add_class('color1')
        self.buttons['complete'].set_sensitive(True)
        self.buttons['complete'].get_style_context().add_class('color3')
        self.buttons['cancel'].set_sensitive(True)
        self.buttons['cancel'].get_style_context().add_class('color2')

    def buttons_not_calibrating(self):
        self.calibrating = False
        self.buttons['start'].get_style_context().add_class('color3')
        self.buttons['start'].set_sensitive(True)

        self.buttons['zpos'].set_sensitive(False)
        self.buttons['zpos'].get_style_context().remove_class('color4')
        self.buttons['zneg'].set_sensitive(False)
        self.buttons['zneg'].get_style_context().remove_class('color1')
        self.buttons['complete'].set_sensitive(False)
        self.buttons['complete'].get_style_context().remove_class('color3')
        if not self.twist_compensate_running:
            self.buttons['cancel'].set_sensitive(False)
            self.buttons['cancel'].get_style_context().remove_class('color2')

    def reset_states(self):
        self.running = False
        self.twist_compensate_running = False
        if self.continue_handler is not None:
            self.buttons['start'].set_label('Start')
            self.buttons['start'].disconnect(self.continue_handler)
            self.continue_handler = None
        if self.start_handler is None:
            if len(self.functions) > 1:
                self.start_handler = self.buttons['start'].connect("clicked", self.on_popover_clicked)
            else:
                self.start_handler = self.buttons['start'].connect("clicked", self.start_calibration, self.functions[0])

    def disable_start_button(self):
        self.buttons['start'].set_sensitive(False)
        self.buttons['start'].get_style_context().remove_class('color3')

    def enable_cancel_button(self):
        self.buttons['cancel'].set_sensitive(True)
        self.buttons['cancel'].get_style_context().add_class('color2')

    def activate(self):
        running = False
        if self._printer.get_stat("axis_twist_compensation", "is_active"):
            self.twist_compensate_running = True
            self.buttons_not_calibrating()
            self.disable_start_button()
            self.enable_cancel_button()
            running = True
        if self._printer.get_stat("manual_probe", "is_active"):
            self.running = True
            self.buttons_calibrating()
            running = True

        if not running:
            self.reset_states()
            self.buttons_not_calibrating()
