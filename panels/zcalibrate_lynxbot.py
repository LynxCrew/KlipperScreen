import logging
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango, GLib
from ks_includes.screen_panel import ScreenPanel
from ks_includes.KlippyGtk import find_widget
from datetime import datetime


class Panel(ScreenPanel):
    widgets = {}
    distances = ['.01', '.05', '.1', '.5', '1', '5']
    distance = distances[-2]

    def __init__(self, screen, title):
        title = title or _("Z Calibrate")
        super().__init__(screen, title)
        self.running = False
        self.calibrating = False
        self.twist_compensate_running = False
        self.start_handler = None
        self.continue_handler = None
        self.bed_mesh_calibrate = (["LEVEL_AUTO", False]
                                   if "LEVEL_AUTO" in self._printer.available_commands
                                   else ["BED_MESH_CALIBRATE", True])
        self.probe_calibrate = (["CALIBRATE_PROBE", False]
                                if "CALIBRATE_PROBE" in self._printer.available_commands
                                else ["PROBE_CALIBRATE", True])
        self.beacon_calibrate = (["CALIBRATE_BEACON", False]
                                 if "CALIBRATE_BEACON" in self._printer.available_commands
                                 else ["BEACON_CALIBRATE", True])
        self.beacon_auto_calibrate = (["AUTO_CALIBRATE_BEACON", False]
                                      if "AUTO_CALIBRATE_BEACON" in self._printer.available_commands
                                      else ["BEACON_AUTO_CALIBRATE", True])
        self.endstop_calibrate = (["CALIBRATE_Z_ENDSTOP", False]
                                  if "CALIBRATE_Z_ENDSTOP" in self._printer.available_commands
                                  else ["Z_ENDSTOP_CALIBRATE", True])
        self.twist_compensation_calibrate = (["CALIBRATE_AXIS_TWIST_COMPENSATION", False]
                                             if "CALIBRATE_AXIS_TWIST_COMPENSATION" in self._printer.available_commands
                                             else ["AXIS_TWIST_COMPENSATION_CALIBRATE", True])
        self.wait_for_continue = False
        if "axis_twist_compensation" in self._printer.get_config_section_list():
            twist_compensation = self._printer.get_config_section(
                "axis_twist_compensation"
            )
            if ('wait_for_continue' in twist_compensation
                    and twist_compensation['wait_for_continue'] == 'true'):
                self.wait_for_continue = True

        self.last_drop_time = datetime.now()
        self.initialize_mesh_params()
        self.initialize_probe_params()
        self.setup_ui()

    def initialize_mesh_params(self):
        self.mesh_min = []
        self.mesh_max = []
        self.mesh_radius = None
        self.mesh_origin = [0, 0]
        self.zero_ref = []
        if "BED_MESH_CALIBRATE" not in self._printer.available_commands:
            return
        mesh = self._printer.get_config_section("bed_mesh")
        if 'mesh_radius' in mesh:
            self.mesh_radius = float(mesh['mesh_radius'])
            if 'mesh_origin' in mesh:
                self.mesh_origin = self._csv_to_array(mesh['mesh_origin'])
        elif 'mesh_min' in mesh and 'mesh_max' in mesh:
            self.mesh_min = self._csv_to_array(mesh['mesh_min'])
            self.mesh_max = self._csv_to_array(mesh['mesh_max'])
        elif 'min_x' in mesh and 'min_y' in mesh and 'max_x' in mesh and 'max_y' in mesh:
            self.mesh_min = [float(mesh['min_x']), float(mesh['min_y'])]
            self.mesh_max = [float(mesh['max_x']), float(mesh['max_y'])]
        if 'zero_reference_position' in self._printer.get_config_section("bed_mesh"):
            self.zero_ref = self._csv_to_array(mesh['zero_reference_position'])

    def initialize_probe_params(self):
        self.z_hop_speed = 15.0
        self.z_hop = 5.0
        self.probe = self._printer.get_probe()
        if self.probe:
            self.x_offset = float(self.probe.get('x_offset', 0.0))
            self.y_offset = float(self.probe.get('y_offset', 0.0))
            self.z_offset = float(self.probe.get('z_offset', 0.0))
            if "sample_retract_dist" in self.probe:
                self.z_hop = float(self.probe['sample_retract_dist'])
            if "speed" in self.probe:
                self.z_hop_speed = float(self.probe['speed'])
        else:
            self.x_offset = 0.0
            self.y_offset = 0.0
            self.z_offset = 0.0
        logging.info(f"Offset X:{self.x_offset} Y:{self.y_offset} Z:{self.z_offset}")

    def setup_ui(self):
        self.widgets['zposition'] = Gtk.Label(label="Z: ?")
        self.widgets['zoffset'] = Gtk.Label(label="?")

        pos = Gtk.Grid(row_homogeneous=True, column_homogeneous=True)
        pos.attach(self.widgets['zposition'], 0, 1, 2, 1)

        if self.probe:
            pos.attach(Gtk.Label(label=_("Probe Offset") + ": "), 0, 2, 2, 1)
            pos.attach(Gtk.Label(label=_("Saved")), 0, 3, 1, 1)
            pos.attach(Gtk.Label(label=_("New")), 1, 3, 1, 1)
            pos.attach(Gtk.Label(label=f"{self.z_offset:.3f}"), 0, 4, 1, 1)
            pos.attach(self.widgets['zoffset'], 1, 4, 1, 1)

        for label in pos.get_children():
            if isinstance(label, Gtk.Label):
                label.set_ellipsize(Pango.EllipsizeMode.END)

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
        self.buttons['cancel'].connect(
            "clicked",
            self._screen._confirm_send_action,
            ("Are you sure you want to stop the calibration?"),
            self.abort
        )

        self.reset_states()

        self.dropdown = Gtk.ComboBox.new_with_model(self.set_commands())
        self.dropdown.connect("changed", self.on_dropdown_change)
        self.dropdown.connect("notify::popup-shown", self.on_popup_shown)
        renderer_text = Gtk.CellRendererText()
        renderer_text.set_property("ellipsize", Pango.EllipsizeMode.END)
        self.dropdown.pack_start(renderer_text, True)
        self.dropdown.add_attribute(renderer_text, "text", 0)
        self.dropdown.set_active(0)

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

        start_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        start_box.pack_start(self.buttons['start'], True, True, 0)
        start_box.pack_start(self.dropdown, True, True, 0)

        grid = Gtk.Grid(column_homogeneous=True)
        if self._screen.vertical_mode:
            zpos_row, zneg_row = (2, 1) if self._config.get_config()["main"].getboolean("invert_z", False) else (1, 2)
            grid.attach(self.buttons['zpos'], 0, zpos_row, 1, 1)
            grid.attach(self.buttons['zneg'], 0, zneg_row, 1, 1)
            grid.attach(start_box, 0, 0, 1, 1)
            grid.attach(pos, 1, 0, 1, 1)
            grid.attach(self.buttons['complete'], 1, 1, 1, 1)
            grid.attach(self.buttons['cancel'], 1, 2, 1, 1)
            grid.attach(distances, 0, 3, 2, 1)
        else:
            zpos_row, zneg_row = (1, 0) if self._config.get_config()["main"].getboolean("invert_z", False) else (0, 1)
            grid.attach(self.buttons['zpos'], 0, zpos_row, 1, 1)
            grid.attach(self.buttons['zneg'], 0, zneg_row, 1, 1)
            grid.attach(start_box, 1, 0, 1, 1)
            grid.attach(pos, 1, 1, 1, 1)
            grid.attach(self.buttons['complete'], 2, 0, 1, 1)
            grid.attach(self.buttons['cancel'], 2, 1, 1, 1)
            grid.attach(distances, 0, 2, 3, 1)

        self.content.add(grid)

    def on_dropdown_change(self, dropdown):
        iterable = dropdown.get_active_iter()
        if iterable is None:
            self._screen.show_popup_message("Unknown error with dropdown")
            return
        model = dropdown.get_model()
        logging.debug(f"Selected {model[iterable][0]}")

    def on_popup_shown(self, combo_box, param):
        if combo_box.get_property("popup-shown"):
            logging.debug("Dropdown popup show")
            self.last_drop_time = datetime.now()
        else:
            elapsed = (datetime.now() - self.last_drop_time).total_seconds()
            if elapsed < 0.2:
                logging.debug(f"Dropdown closed too fast ({elapsed}s)")
                GLib.timeout_add(50, self.dropdown_keep_open)
                return
            logging.debug("Dropdown popup close")

    def dropdown_keep_open(self):
        self.dropdown.popup()
        return False

    def set_commands(self):
        commands = Gtk.ListStore(str)

        if "PROBE_CALIBRATE" in self._printer.available_commands:
            commands.append(self.probe_calibrate)
        if "BEACON_CALIBRATE" in self._printer.available_commands:
            commands.append(self.beacon_calibrate)
        if "BEACON_AUTO_CALIBRATE" in self._printer.available_commands:
            commands.append(self.beacon_auto_calibrate)
        if "Z_ENDSTOP_CALIBRATE" in self._printer.available_commands:
            commands.append({self.endstop_calibrate})
        if "BED_MESH_CALIBRATE" in self._printer.available_commands:
            commands.append(["BED_MESH_CALIBRATE METHOD=manual", True])
        if "DELTA_CALIBRATE" in self._printer.available_commands:
            commands.append(["DELTA_CALIBRATE", True])
            commands.append(["DELTA_CALIBRATE METHOD=manual", True])
        if "AXIS_TWIST_COMPENSATION_CALIBRATE" in self._printer.available_commands:
            commands.append(self.twist_compensation_calibrate)

        # Custom commands
        if self.ks_printer_cfg is not None:
            if custom_config := self.ks_printer_cfg.get("zcalibrate_custom_commands", None):
                custom_commands = [str(i.strip()) for i in custom_config.split(',')]
                for command in custom_commands:
                    commands.append([f"{command}", True])

        logging.info(f"Available commands for calibration: {[row[0] for row in commands]}")
        return commands

    @staticmethod
    def _csv_to_array(string):
        return [float(i.strip()) for i in string.split(',')]

    def start_calibration(self, widget):
        iterable = self.dropdown.get_active_iter()
        if iterable is None:
            self._screen.show_popup_message("Unknown error with dropdown")
            return
        model = self.dropdown.get_model()
        command = model[iterable][0]

        self.disable_start_button()

        self.running = True

        self.dropdown.set_sensitive(False)

        self._screen._ws.klippy.gcode_script("SET_GCODE_OFFSET Z=0")
        self._screen._ws.klippy.gcode_script("BED_MESH_CLEAR")
        if command[1]:
            if self._printer.get_stat("toolhead", "homed_axes") != "xyz":
                self._screen._ws.klippy.gcode_script("G28")
            self._move_to_position(*self._get_calibration_location())
        self._screen._ws.klippy.gcode_script(command)

    def _move_to_position(self, x, y):
        if not x or not y:
            self._screen.show_popup_message(_("Error: Couldn't get a position to probe"))
            return
        logging.info(f"Lifting Z: {self.z_hop}mm {self.z_hop_speed}mm/s")
        self._screen._ws.klippy.gcode_script(f"G91\nG0 Z{self.z_hop} F{self.z_hop_speed * 60}")
        logging.info(f"Moving to X:{x} Y:{y}")
        self._screen._ws.klippy.gcode_script(f'G90\nG0 X{x} Y{y} F3000')

    def _get_calibration_location(self):
        if self.ks_printer_cfg is not None:
            x = self.ks_printer_cfg.getfloat("calibrate_x_position", None)
            y = self.ks_printer_cfg.getfloat("calibrate_y_position", None)
            if x and y:
                logging.debug(f"Using KS configured position: {x}, {y}")
                return x, y

        if self.zero_ref:
            logging.debug(f"Using zero reference position: {self.zero_ref}")
            return self.zero_ref[0] - self.x_offset, self.zero_ref[1] - self.y_offset

        if ("safe_z_home" in self._printer.get_config_section_list() and
                "Z_ENDSTOP_CALIBRATE" not in self._printer.available_commands):
            return self._get_safe_z()
        if self.mesh_radius or "delta" in self._printer.get_config_section("printer")['kinematics']:
            logging.info(f"Round bed calibrating at {self.mesh_origin}")
            return self.mesh_origin[0] - self.x_offset, self.mesh_origin[1] - self.y_offset

        x, y = self._calculate_position()
        return x, y

    def _get_safe_z(self):
        safe_z = self._printer.get_config_section("safe_z_home")
        safe_z_xy = self._csv_to_array(safe_z['home_xy_position'])
        logging.debug(f"Using safe_z {safe_z_xy[0]}, {safe_z_xy[1]}")
        if 'z_hop' in safe_z:
            self.z_hop = float(safe_z['z_hop'])
        if 'z_hop_speed' in safe_z:
            self.z_hop_speed = float(safe_z['z_hop_speed'])
        return safe_z_xy[0], safe_z_xy[1]

    def _calculate_position(self):
        if self.mesh_max and self.mesh_min:
            mesh_mid_x = (self.mesh_min[0] + self.mesh_max[0]) / 2
            mesh_mid_y = (self.mesh_min[1] + self.mesh_max[1]) / 2
            logging.debug(f"Probe in the mesh center X:{mesh_mid_x} Y:{mesh_mid_y}")
            return mesh_mid_x - self.x_offset, mesh_mid_y - self.y_offset
        try:
            mid_x = float(self._printer.get_config_section("stepper_x")['position_max']) / 2
            mid_y = float(self._printer.get_config_section("stepper_y")['position_max']) / 2
        except KeyError:
            logging.error("Couldn't get max position from stepper_x and stepper_y")
            return None, None
        logging.debug(f"Probe in the center X:{mid_x} Y:{mid_y}")
        return mid_x - self.x_offset, mid_y - self.y_offset

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
            if "manual_probe" in data:
                if data["manual_probe"]["is_active"]:
                    self.buttons_calibrating()
                else:
                    self.buttons_not_calibrating()
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
                self._screen.show_popup_message(
                    _("Failed, adjust position first"))
                self.reset_states()
                self.buttons_not_calibrating()
                logging.info(data)
            elif "use testz" in data or "use abort" in data or "z position" in data:
                self.buttons_calibrating()
        return

    def update_position(self, position):
        self.widgets['zposition'].set_text(f"Z: {position[2]:.3f}")
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
        self.dropdown.set_sensitive(False)

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
        self.dropdown.set_sensitive(True)

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
            self.start_handler = self.buttons['start'].connect("clicked", self.start_calibration)

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
            self.enable_cancel_button()
            running = True
        if self._printer.get_stat("manual_probe", "is_active"):
            self.running = True
            self.buttons_calibrating()
            running = True

        if not running:
            self.reset_states()
            self.buttons_not_calibrating()
