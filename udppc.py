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

port = 22000 #порт для приема по udp
stop_port = 55000 #порт для чтения сигнала stop

class CustomData():
    def __init__(self):
        Gst.init(None)

        self._pipeline = Gst.Pipeline.new("pipeline")
        self._udpsrc = Gst.ElementFactory.make("udpsrc", "source") 
        self._exit_flag = multiprocessing.Event()
        self._frame_queue = multiprocessing.Queue(maxsize=2)  # Очередь для кадров
        self._rtph264depay = Gst.ElementFactory.make("rtph264depay", "depay")
        self._h264parse = Gst.ElementFactory.make("h264parse", "parser")
        self._avdec_h264 = Gst.ElementFactory.make("avdec_h264", "decoder")
        self._videoconvert = Gst.ElementFactory.make("videoconvert", "converter")
        self._appsink = Gst.ElementFactory.make("appsink", "sink")

        if not all([self._pipeline, self._udpsrc, self._rtph264depay, self._h264parse, self._avdec_h264, self._videoconvert, self._appsink]):
            raise RuntimeError("Ошибка создания элементов")
        
        self._udpsrc.set_property("port", port)
        self._udpsrc.set_property("caps", Gst.Caps.from_string("application/x-rtp,media=video,encoding-name=H264")) #формат 
        self._appsink.set_property("emit-signals", True)
        self._appsink.set_property("sync", False)
        self._appsink.set_property("max-buffers", 1)
        self._appsink.connect("new-sample", self.on_frame)

        self._pipeline.add(self._udpsrc)
        self._pipeline.add(self._rtph264depay)
        self._pipeline.add(self._h264parse)
        self._pipeline.add(self._avdec_h264)
        self._pipeline.add(self._videoconvert)
        self._pipeline.add(self._appsink)

        self._udpsrc.link(self._rtph264depay)
        self._rtph264depay.link(self._h264parse)
        self._h264parse.link(self._avdec_h264)
        self._avdec_h264.link(self._videoconvert)
        self._videoconvert.link(self._appsink)

        self._stop_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop_socket.bind(("", stop_port))

        threading.Thread(target=self.listen_for_stop_signal, daemon=True).start()

        self._frame_thread = None
    
    #функция обработки кадра
    def on_frame(self, appsink): 
        sample = appsink.emit("pull-sample")  # Извлекаем кадр из потока
        if sample:
            buffer = sample.get_buffer()
            caps = sample.get_caps()  # Получаем параметры кадра
            width = caps.get_structure(0).get_value("width")
            height = caps.get_structure(0).get_value("height")

            success, mapinfo = buffer.map(Gst.MapFlags.READ)  # Читаем данные кадра
            if success:
                frame = numpy.frombuffer(mapinfo.data, dtype=numpy.uint8)  # Преобразуем байты в numpy

                # Обрабатываем YUV формат (I420)
                if frame.size == width * height * 3 // 2:  # I420
                    yuv_frame = frame.reshape((height * 3 // 2, width))
                    rgb_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)  # Преобразуем в RGB
                else:
                    print(f"Неизвестный формат данных, размер: {frame.size}")
                    buffer.unmap(mapinfo)
                    return Gst.FlowReturn.ERROR

                buffer.unmap(mapinfo)

                # Добавляем кадр в очередь
                try:
                    if not self._frame_queue.full():
                        self._frame_queue.put_nowait(rgb_frame)
                    else:
                        self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
                except queue.Full:
                    pass

        return Gst.FlowReturn.OK

    # Метод для получения кадра из очереди
    def get(self): 
        try:
            frame = self._frame_queue.get(timeout=1)  # Тайм-аут на 1 секунду
            return frame
        except queue.Empty:
            return None  # Возвращаем None, если очередь пуста
        
    def start(self):
        print("Запуск")
        self._pipeline.set_state(Gst.State.PLAYING)
        loop = GLib.MainLoop()
        self._frame_thread = multiprocessing.Process(target=self._start, args=(loop, self._exit_flag))
        self._frame_thread.start()
    
    #чтение сигнала остановки
    def listen_for_stop_signal(self):   
        while True:
            data, _ = self._stop_socket.recvfrom(1024)
            if data.decode().strip() == "stop":
                print("\nПолучен сигнал остановки, завершаем...")
                self.stop()
    
    # Метод для корректного завершения работы
    def stop(self):
        print("Остановка видеопотока...")
        self._exit_flag.set()  # Устанавливаем флаг для выхода из цикла
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)  # Останавливаем pipeline

        if self._frame_thread is not None:
            self._frame_thread.join()  # Ждем завершения фонового потока
    
        print("Поток остановлен")

    def _start(self, loop, exit_flag):
        try:
            print("Pipeline запущен.")
            while not exit_flag.is_set():  # Основной цикл продолжается до выхода
                loop.get_context().iteration(False)
        except KeyboardInterrupt:
            self.stop()
        
    def __del__(self):
        self.stop()

if __name__ == "__main__":
    player = CustomData()
    player.start()

    try:
        while not player._exit_flag.is_set():  # Проверяем флаг остановки
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
