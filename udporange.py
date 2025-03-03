import gi
import time
import threading
import sys
import socket

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GLib

host = "192.168.1.134"
port = 20000
stop_port = 55000

class CustomData():
    def __init__(self):
        Gst.init(None)

        self.pipeline = Gst.Pipeline.new("pipeline")
        self.v4l2src = Gst.ElementFactory.make("v4l2src", "source")
        self.videoconvert = Gst.ElementFactory.make("videoconvert", "converter")
        self.videoscale = Gst.ElementFactory.make("videoscale", "videoscale")
        self.caps = Gst.ElementFactory.make("capsfilter", "caps")
        self.mpph264enc = Gst.ElementFactory.make("mpph264enc", "encoder")
        self.h264parse = Gst.ElementFactory.make("h264parse", "parser")
        self.rtph264pay = Gst.ElementFactory.make("rtph264pay", "rtph264pay")
        self.udpsink = Gst.ElementFactory.make("udpsink", "sink")

        if not all([self.pipeline, self.v4l2src, self.videoconvert, self.videoscale, self.caps, 
                    self.mpph264enc, self.h264parse, self.rtph264pay, self.udpsink]):
            raise RuntimeError("Ошибка создания элементов")

        self.v4l2src.set_property("device", "/dev/video0")
        self.caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=720,height=576"))
        self.mpph264enc.set_property("bps", 5000000)  # 5 Мбит/с
        self.mpph264enc.set_property("rc-mode", "cbr")  # Постоянный битрейт
        self.mpph264enc.set_property("level", 30) #3 level
        self.mpph264enc.set_property("profile", 77) #main profile
        self.mpph264enc.set_property("qp-delta-ip", 1)
        self.udpsink.set_property("host", host)
        self.udpsink.set_property("port", port)

        self.pipeline.add(self.v4l2src)
        self.pipeline.add(self.videoconvert)
        self.pipeline.add(self.videoscale)
        self.pipeline.add(self.caps)
        self.pipeline.add(self.mpph264enc)
        self.pipeline.add(self.h264parse)
        self.pipeline.add(self.rtph264pay)
        self.pipeline.add(self.udpsink)

        self.v4l2src.link(self.videoconvert)
        self.videoconvert.link(self.videoscale)
        self.videoscale.link(self.caps)
        self.caps.link(self.mpph264enc)
        self.mpph264enc.link(self.h264parse)
        self.h264parse.link(self.rtph264pay)
        self.rtph264pay.link(self.udpsink)

        self.running = False
        self.start_time = 0
        self.time_thread = None
        self.stop = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start_pipeline(self):
        print("Запуск...")
        self.pipeline.set_state(Gst.State.PLAYING)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.running = True

    def stop_pipeline(self):
        self.send_stop()
        self.running = False
        print("Остановка...")
        self.pipeline.set_state(Gst.State.NULL)
        loop.quit()
    
    def send_stop(self):
        self.stop.sendto(b"stop", (host, stop_port))
        print("Сигнал остановки отправлен.")

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, debug_info = message.parse_error()
            print(f"Ошибка: {err}, детали: {debug_info}")
            self.stop_pipeline()
        elif message.type == Gst.MessageType.EOS:
            print("Завершение воспроизведения.")

if __name__ == "__main__":
    data = CustomData()
    try:
        data.start_pipeline()
        loop = GLib.MainLoop()
        loop.run()
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
    finally:
        data.stop_pipeline()
