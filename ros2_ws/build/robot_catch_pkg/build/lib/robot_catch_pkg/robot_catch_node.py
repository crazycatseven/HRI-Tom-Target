import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray
from cv_bridge import CvBridge
import random
from gtts import gTTS
import subprocess
import os
import cv2

class RobotState:
    START = 'START'
    ROTATE = 'ROTATE'
    STOP = 'STOP'
    APPROACH = 'APPROACH'
    CATCH = 'CATCH'
    BACK = 'BACK'
    END = 'END'


class RobotCatchGame(Node):
    def __init__(self):
        super().__init__('robot_catch_game')

        # State initialize
        self.state = RobotState.START
        self.state_ts = self.get_clock().now()
        self.round_count = 0
        self.new_round = True
        self.rotate_time = 10 # random number for each round (5-15)
        self.music_process = None

        # Robot parameters
        self.SPEED_LINEAR = 0.2
        self.SPEED_ANGULAR = 1.0
        self.WALK_TIME = 3.0
        self.TOTAL_ROUNDS = 3
        self.ROTATE_180_TIME = 3.1415926 / self.SPEED_ANGULAR  # time to rotate 180 degrees
        
        # Audio file path
        self.START_FILE = "/home/ubuntu/HRI-Tom-Target/ros2_ws/src/audio/start.mp3"
        self.MUSIC_FILE = "/home/ubuntu/HRI-Tom-Target/ros2_ws/src/audio/tom_jerry.mp3"
        self.CATCH_FILE = "/home/ubuntu/HRI-Tom-Target/ros2_ws/src/audio/catch.mp3"
        self.MAGIC_FILE = "/home/ubuntu/HRI-Tom-Target/ros2_ws/src/audio/magic.mp3"
        self.FAIL_FILE = "/home/ubuntu/HRI-Tom-Target/ros2_ws/src/audio/fail.mp3"

        # Sensor data storage
        self.last_rgb_image = None
        self.detected_persons = []
        self.image_center_x = 0
        self.br = CvBridge()

        # Initialize subscribers
        self.rgb_sub = self.create_subscription(
            Image,
            '/color/image',
            self.rgb_callback,
            10)

        self.person_detection_sub = self.create_subscription(
            Detection2DArray,
            '/color/mobilenet_detections',
            self.person_detection_callback,
            10)
            
        # Initialize publisher and control timer
        self.vel_pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.timer = self.create_timer(0.05, self.control_cycle)

        self.get_logger().info('Robot Catch Node initialized')

    def rgb_callback(self, msg):
        """Get RGB image and display detected persons"""

        self.last_rgb_image = self.br.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.image_center_x = self.last_rgb_image.shape[1] // 2

    def person_detection_callback(self, msg):
        """Process person detections using YOLO"""

        # Clear previous results
        self.detected_persons = []

        for detection in msg.detections:
            if detection.id == '15':
                center_x = detection.bbox.center.position.x
                center_y = detection.bbox.center.position.y
                width = detection.bbox.size_x
                height = detection.bbox.size_y

                person_position = {
                    "top_left": (int(center_x - width/2), int(center_y - height/2)),
                    "bottom_right": (int(center_x + width/2), int(center_y + height/2)),
                    "center_x": int(center_x),
                }

                self.detected_persons.append(person_position)

                break

    
    def control_cycle(self):
        self.get_logger().info(f"State: {self.state}, Round #{self.round_count} / {self.TOTAL_ROUNDS}")

        out_vel = Twist()

        if self.state == RobotState.START:
            # if self.last_rgb_image is not None:
            self.go_state(RobotState.ROTATE)


        elif self.state == RobotState.ROTATE:
            # if self.round_count == self.TOTAL_ROUNDS: 
            #     self.go_state(RobotState.END)

            # Assign a random rotation duration to each round
            if self.new_round:
                if self.round_count == self.TOTAL_ROUNDS: 
                    self.go_state(RobotState.END)

                self.play_audio(self.START_FILE)
                self.rotate_time = random.randint(5, 15)
                self.round_count += 1
                self.new_round = False
                self.play_music()

            out_vel.angular.z = self.SPEED_ANGULAR
            
            elapsed = self.get_clock().now() - self.state_ts
            if elapsed >= Duration(seconds=self.rotate_time):
                self.get_logger().info(
                    f"Rotate time: {elapsed.nanoseconds / 1e9:.2f} / {self.rotate_time}, Detect: {self.detected_persons}"
                )
                self.go_state(RobotState.STOP)
                

        elif self.state == RobotState.APPROACH:
            out_vel.linear.x = self.SPEED_LINEAR
            elapsed = self.get_clock().now() - self.state_ts
            if elapsed >= Duration(seconds=self.WALK_TIME):
                self.go_state(RobotState.CATCH)


        elif self.state == RobotState.CATCH:
            self.play_audio(self.CATCH_FILE)

            if not self.detected_persons:
                self.go_state(RobotState.BACK)


        elif self.state == RobotState.STOP:
            self.stop_music()

            # if self.detected_persons:
            if True: # TODO: for test purpose only
                self.play_audio(self.MAGIC_FILE)
                self.go_state(RobotState.APPROACH)
            else:
                self.play_audio(self.FAIL_FILE)
                self.new_round = True
                self.go_state(RobotState.ROTATE)

        
        elif self.state == RobotState.BACK:
            # Back has two phases:
            # 1. Rotate 180 degrees -> back_phase = 'rotate'
            # 2. Walk forward       -> back_phase = 'forward'

            if not hasattr(self, 'back_phase'):
                self.back_phase = 'rotate'
            
            # Rotate phase
            if self.back_phase == 'rotate':
                out_vel.angular.z = self.SPEED_ANGULAR
                elapsed = self.get_clock().now() - self.state_ts
                if elapsed >= Duration(seconds=self.ROTATE_180_TIME):
                    self.back_phase = 'forward'
                    self.state_ts = self.get_clock().now()
            # Forward phase
            else:
                out_vel.linear.x = self.SPEED_LINEAR
                elapsed = self.get_clock().now() - self.state_ts
                if elapsed >= Duration(seconds=self.WALK_TIME):
                    self.back_phase = 'rotate'
                    self.new_round = True
                    self.go_state(RobotState.ROTATE)
                    

        elif self.state == RobotState.END:
            return

        self.vel_pub.publish(out_vel)

    def go_state(self, new_state):
        self.state = new_state
        self.state_ts = self.get_clock().now()

    def play_music(self):
        if self.music_process is None:
            try:
                self.music_process = subprocess.Popen(['mpg123', '-q', '-o', 'alsa', '-a', 'hw:1,0', self.MUSIC_FILE])
                self.get_logger().info("Playing music.")
            except Exception as e:
                self.get_logger().error(f"Music playback failed: {e}")

    def stop_music(self):
        if self.music_process:
            self.music_process.terminate()
            self.music_process = None
            self.get_logger().info("Stopped music.")

    def play_audio(self, audio_file):
        try:
            os.system(f"mpg123 -o alsa -a hw:1,0 {audio_file}")
            self.get_logger().info("Robot plays audio")
        except Exception as e:
                self.get_logger().error(f"Catch audio playback failed: {e}")


def main(args=None):
    rclpy.init(args=args)

    robot_catch_node = RobotCatchGame()

    rclpy.spin(robot_catch_node)

    robot_catch_node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()