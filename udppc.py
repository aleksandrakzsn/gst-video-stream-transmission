import gi
import threading
import socket
import cv2
import multiprocessing
import queue
import numpy

gi.require_version('Gst', '1.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gst, GLib

stop_port = 55000

class CustomData():
    def __init__(self):
        Gst.init(None)

        self.pipeline = Gst.Pipeline.new("pipeline")
        self.udpsrc = Gst.ElementFactory.make("udpsrc", "source")
        self.exit_flag = multiprocessing.Event()
        self.frame_queue = multiprocessing.Queue(maxsize=2)  # Очередь для кадров
        self.rtph264depay = Gst.ElementFactory.make("rtph264depay", "depay")
        self.h264parse = Gst.ElementFactory.make("h264parse", "parser")
        self.avdec_h264 = Gst.ElementFactory.make("avdec_h264", "decoder")
        self.videoconvert = Gst.ElementFactory.make("videoconvert", "converter")
        self.appsink = Gst.ElementFactory.make("appsink", "sink")

        if not all([self.pipeline, self.udpsrc, self.rtph264depay, self.h264parse, self.avdec_h264, self.videoconvert, self.appsink]):
            raise RuntimeError("Ошибка создания элементов")
        
        self.udpsrc.set_property("port", 20000)
        self.udpsrc.set_property("caps", Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264"))
        self.appsink.set_property("emit-signals", True)
        self.appsink.set_property("sync", False)
        self.appsink.set_property("max-buffers", 1)
        self.appsink.connect("new-sample", self.on_frame)

        self.pipeline.add(self.udpsrc)
        self.pipeline.add(self.rtph264depay)
        self.pipeline.add(self.h264parse)
        self.pipeline.add(self.avdec_h264)
        self.pipeline.add(self.videoconvert)
        self.pipeline.add(self.appsink)

        self.udpsrc.link(self.rtph264depay)
        self.rtph264depay.link(self.h264parse)
        self.h264parse.link(self.avdec_h264)
        self.avdec_h264.link(self.videoconvert)
        self.videoconvert.link(self.appsink)

        self.stop_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stop_socket.bind(("", stop_port))

        threading.Thread(target=self.listen_for_stop_signal, daemon=True).start()

        self.frame_thread = None
    
    def on_frame(self, appsink):
        sample = appsink.emit("pull-sample") # pull-sample — сигнал GStreamer, который позволяет извлечь один кадр из потока
        if sample:
            buffer = sample.get_buffer()
            caps = sample.get_caps() #получение данных о кадре
            width = caps.get_structure(0).get_value("width")
            height = caps.get_structure(0).get_value("height")

            success, mapinfo = buffer.map(Gst.MapFlags.READ) # success - успех операции, mapinfo - информация о кадре из буфера (mapinfo.data – сырые байты кадра.mapinfo.size – размер данных в буфере.)
            if success:
                frame = numpy.frombuffer(mapinfo.data, dtype=numpy.uint8) #преобразование байтов из буфера в массив numpy с типом данных uint8_t

                # Обрабатываем YUV формат (I420)
                if frame.size == width * height * 3 // 2:  #I420
                    yuv_frame = frame.reshape((height * 3 // 2, width))
                    rgb_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)  # Преобразуем I420 в RGB
                else:
                    print(f"Неизвестный формат данных, размер: {frame.size}")
                    buffer.unmap(mapinfo)
                    return Gst.FlowReturn.ERROR

                buffer.unmap(mapinfo)

                # Добавляем кадр в очередь
                try:
                    if not self.frame_queue.full():
                        self.frame_queue.put_nowait(rgb_frame)
                    else:
                        self.frame_queue.get_nowait()
                except queue.Empty:
                    pass
                except queue.Full:
                    pass

        return Gst.FlowReturn.OK

    def get(self):
        # Метод для получения кадра из очереди
        try:
            frame = self.frame_queue.get(timeout=1)  # Тайм-аут на 1 секунду
            return frame
        except queue.Empty:
            return None  # Возвращаем None, если очередь пуста
        
    def start(self):
        print("Запуск")
        self.pipeline.set_state(Gst.State.PLAYING)
        loop = GLib.MainLoop()
        self.frame_thread = multiprocessing.Process(target=self._start, args=(loop, self.exit_flag))
        self.frame_thread.start()
    
    def listen_for_stop_signal(self):
        while True:
            data, _ = self.stop_socket.recvfrom(1024)
            if data.decode().strip() == "stop":
                print("\nПолучен сигнал остановки, завершаем...")
                self.stop()
    
    def stop(self):
        # Метод для корректного завершения работы
        print("Остановка видеопотока...")
        self.exit_flag.set()  # Устанавливаем флаг для выхода из цикла
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)  # Останавливаем pipeline

        if self.frame_thread is not None:
            self.frame_thread.join()  # Ждем завершения фонового потока
    
        print("Поток остановлен")

    def _start(self, loop, exit_flag):
        try:
            print("Pipeline запущен.")
            while not exit_flag:  # Основной цикл продолжается до выхода
                # Проверяем наличие кадров и сообщений
                loop.get_context().iteration(False)
        except KeyboardInterrupt:
            self.stop()
        
    def __del__(self):
        self.stop()

if __name__ == "__main__":
    player = CustomData()
    player.start()

    try:
        while not player.exit_flag.is_set():  # Проверяем флаг остановки
            image = player.get()
            if image is not None and image.size > 0:  # Проверяем, что кадр не пустой
                cv2.imshow("image", image)
            cv2.waitKey(1)
                
    except KeyboardInterrupt:
        print("Прервано пользователем")
        player.stop()

    finally:
        # Очистка ресурсов OpenCV
        cv2.destroyAllWindows()
