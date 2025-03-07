import gi
import socket

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GLib

host = "192.168.1.134" #ip хоста для первого потока
port = 20000 #порт для первого потока
stop_port = 55000 #порт для сигнала stop
second_host = "192.168.1.134" #ip для второго потока
second_port = 24000 #порт для второго потока

class CustomData():
    def __init__(self):
        Gst.init(None)

        self._pipeline = Gst.Pipeline.new("pipeline")
        self._v4l2src = Gst.ElementFactory.make("v4l2src", "source")
        self._tee = Gst.ElementFactory.make("tee", "tee") 
        self._qpc = Gst.ElementFactory.make("queue", "q1") #Очередь для первого потока
        self._qor = Gst.ElementFactory.make("queue", "q2") #Очередь для второго потока
        
        #Первый поток, вывод на ПК
        self._videoconvert = Gst.ElementFactory.make("videoconvert", "converter")
        self._videoscale = Gst.ElementFactory.make("videoscale", "videoscale")
        self._caps = Gst.ElementFactory.make("capsfilter", "caps")
        self._mpph264enc = Gst.ElementFactory.make("mpph264enc", "encoder")
        self._h264parse = Gst.ElementFactory.make("h264parse", "parser")
        self._rtph264pay = Gst.ElementFactory.make("rtph264pay", "rtph264pay")
        self._udpsink = Gst.ElementFactory.make("udpsink", "sink")

        #Второй поток
        self._videoconvert_sec = Gst.ElementFactory.make("videoconvert", "convert")
        self._videoscale_sec = Gst.ElementFactory.make("videoscale", "videosc")
        self._caps_sec = Gst.ElementFactory.make("capsfilter", "capss")
        self._mpph264enc_sec = Gst.ElementFactory.make("mpph264enc", "enc")
        self._h264parse_sec = Gst.ElementFactory.make("h264parse", "parse")
        self._rtph264pay_sec = Gst.ElementFactory.make("rtph264pay", "pay")
        self._udpsink_sec = Gst.ElementFactory.make("udpsink", "udpsink")
        
        if not all([self._pipeline, self._v4l2src, self._tee, self._qpc, self._videoconvert, self._videoscale, self._caps, 
                    self._mpph264enc, self._h264parse, self._rtph264pay, self._udpsink, self._videoconvert_sec, self._videoscale_sec, self._caps_sec,
                    self._mpph264enc_sec, self._h264parse_sec, self._rtph264pay_sec, self._udpsink_sec]):
            raise RuntimeError("Ошибка создания элементов")

        # Параметры 
        self._v4l2src.set_property("device", "/dev/video0") # Устройство
        self._caps.set_property("caps", Gst.Caps.from_string("video/x-raw,width=720,height=576")) # параметры видео (формат, разрешение)
        self._mpph264enc.set_property("bps", 5000000)  # 5 Мбит/с
        self._mpph264enc.set_property("rc-mode", "cbr")  # Постоянный битрейт
        self._mpph264enc.set_property("level", 30) #3 level
        self._mpph264enc.set_property("profile", 77) #main profile
        self._mpph264enc.set_property("qp-delta-ip", 1) # Соотношение качества I-кадров и P-кадров
        self._udpsink.set_property("host", host) #ip
        self._udpsink.set_property("port", port) #порт
        
        # Параметры для второго потока
        self._caps_sec.set_property("caps", Gst.Caps.from_string("video/x-raw,width=480,height=352"))
        self._mpph264enc_sec.set_property("bps", 1000000)  # 1 Мбит/с
        self._mpph264enc_sec.set_property("rc-mode", "cbr")  # Постоянный битрейт
        self._mpph264enc_sec.set_property("level", 22) #2.2 level
        self._mpph264enc_sec.set_property("profile", 66) #baseline profile
        self._mpph264enc_sec.set_property("qp-delta-ip", 1)
        self._udpsink_sec.set_property("host", second_host)
        self._udpsink_sec.set_property("port", second_port)

        # Добавление в pipeline
        self._pipeline.add(self._v4l2src)
        self._pipeline.add(self._tee)
        self._pipeline.add(self._qpc)
        self._pipeline.add(self._videoconvert)
        self._pipeline.add(self._videoscale)
        self._pipeline.add(self._caps)
        self._pipeline.add(self._mpph264enc)
        self._pipeline.add(self._h264parse)
        self._pipeline.add(self._rtph264pay)
        self._pipeline.add(self._udpsink)
        
        self._pipeline.add(self._qor)
        self._pipeline.add(self._videoconvert_sec)
        self._pipeline.add(self._videoscale_sec)
        self._pipeline.add(self._caps_sec)
        self._pipeline.add(self._mpph264enc_sec)
        self._pipeline.add(self._h264parse_sec)
        self._pipeline.add(self._rtph264pay_sec)
        self._pipeline.add(self._udpsink_sec)
        
        # Соединение элементов
        self._v4l2src.link(self._tee)
        self._qpc.link(self._videoconvert)
        self._videoconvert.link(self._videoscale)
        self._videoscale.link(self._caps)
        self._caps.link(self._mpph264enc)
        self._mpph264enc.link(self._h264parse)
        self._h264parse.link(self._rtph264pay)
        self._rtph264pay.link(self._udpsink)
        
        self._qor.link(self._videoconvert_sec)
        self._videoconvert_sec.link(self._videoscale_sec)
        self._videoscale_sec.link(self._caps_sec)
        self._caps_sec.link(self._mpph264enc_sec)
        self._mpph264enc_sec.link(self._h264parse_sec)
        self._h264parse_sec.link(self._rtph264pay_sec)
        self._rtph264pay_sec.link(self._udpsink_sec)
        
        # Создание src pad tee-элемента
        tee_pc_pad = self._tee.request_pad_simple("src_%u")
        queue_pc_pad = self._qpc.get_static_pad("sink")
        tee_pc_pad.link(queue_pc_pad)
        
        tee_orange_pad = self._tee.request_pad_simple("src_%u")
        queue_orange_pad = self._qor.get_static_pad("sink")
        tee_orange_pad.link(queue_orange_pad)
        
        self.running = False
        self.stop = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.loop = GLib.MainLoop()

    # Функция запуска pipeline
    def start_pipeline(self):
        print("Запуск...")
        self._pipeline.set_state(Gst.State.PLAYING)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.running = True

    # Остановкка pipeline
    def stop_pipeline(self):
        self.send_stop()
        self.running = False
        print("Остановка...")
        self._pipeline.set_state(Gst.State.NULL)
        self.loop.quit()
    
    #Отправка сигнала stop хосту
    def send_stop(self):
        self.stop.sendto(b"stop", (host, stop_port))
        print("Сигнал остановки отправлен.")

    #Чтение шины
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
        data.loop.run()
    except KeyboardInterrupt:
        print("\nПрервано пользователем.")
    finally:
        data.stop_pipeline()
