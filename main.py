import argparse
import cv2
import depthai as dai
import numpy as np
import pyvirtualcam

class Params:
    def __init__(self):
        self.mirror = False
        self.focus = 100
        self.translucent_size = 40  # translucent area size
        self.blur = 67              # mask blur intensity
        self.dilate = 4             # mask dilation size

    def print(self):
        print('mirror:', self.mirror)
        print('focus:', self.focus)
        print('translucent_size:', self.translucent_size)
        print('blur:', self.blur)
        print('dilate:', self.dilate)

    def edit(self, key):
        if key == ord('p'):
            self.print()

        if key == ord('m'):
            self.mirror = not self.mirror
            print('mirror:', self.mirror)

        if key == ord('b'):
            self.blur += 2
            print('blur:', self.blur)

        if key == ord('B') and self.blur > 1:
            self.blur -= 2
            print('blur:', self.blur)

        if key == ord('d'):
            self.dilate += 1
            print('dilate:', self.dilate)

        if key == ord('D') and self.dilate > 0:
            self.dilate -= 1
            print('dilate:', self.dilate)

        if key == ord('f') and self.focus < 256:
            self.focus += 10
            print('focus:', self.focus)

        if key == ord('F') and self.focus > 10:
            self.focus -= 10
            print('focus:', self.focus)

        if key == ord('t') and self.translucent_size < 256:
            self.translucent_size += 10
            print('translucent_size:', self.translucent_size)

        if key == ord('T') and self.translucent_size > 0:
            self.translucent_size -= 10
            print('translucent_size:', self.translucent_size)

params = Params()

# Create a pipeline
def create_pipeline():
    pipeline = dai.Pipeline()

    cam = pipeline.createColorCamera()
    isp_xout = pipeline.createXLinkOut()
    isp_xout.setStreamName("cam")
    cam.isp.link(isp_xout.input)

    left = pipeline.createMonoCamera()
    left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    left.setBoardSocket(dai.CameraBoardSocket.LEFT)

    right = pipeline.createMonoCamera()
    right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    right.setBoardSocket(dai.CameraBoardSocket.RIGHT)

    stereo = pipeline.createStereoDepth()
    stereo.setDepthAlign(dai.CameraBoardSocket.RGB)

    left.out.link(stereo.left)
    right.out.link(stereo.right)

    xout_disp = pipeline.createXLinkOut()
    xout_disp.setStreamName("disparity")

    stereo.disparity.link(xout_disp.input)
    return pipeline

# Resize the frame to 360*360
def resize(frame):
    h = frame.shape[0]
    w  = frame.shape[1]
    d = int((w-h) / 2)
    return cv2.resize(frame[0:h, d:w-d], (360, 360))

# Convert disparity from 0-95 to 0-255
def to_grayscale(frame):
    multiplier = 255 / 95
    frame = (frame * multiplier).astype(np.uint8)
    return frame

# Create a mask
def to_mask(frame):
    frame = cv2.medianBlur(frame, params.blur)
    frame = cv2.dilate(frame, np.empty(0, np.uint8), iterations=params.dilate)
    frame = np.where(frame > params.focus, 255, frame)
    frame = np.where(frame < params.focus - params.translucent_size, 0, frame)
    return frame / 255.0

# Apply the mask to the image
def apply_mask(img, mask):
    masked = np.zeros(img.shape)
    for i in range(3):
      masked[:,:,i] = img[:,:,i] * mask

    return masked.astype('uint8')

# Read the background image
def read_background_image(background_image_path):
    background = cv2.imread(background_image_path)
    return resize(background)

# Get the background image
def get_background(frame):
    if background_image is not None:
        return background_image

    # If no background image is specified, use a blurred frame instead
    return cv2.GaussianBlur(frame, (99, 99), 0)

# Convert to an image for a virtual camera
def to_vcam_image(img):
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Make it a rectangle (640*360) with margins on both sides
    return cv2.copyMakeBorder(img, 0, 0, 140, 140, cv2.BORDER_CONSTANT, (0, 0, 0))


parser = argparse.ArgumentParser()
parser.add_argument('-b', '--background', help="Path to background image file")
args = parser.parse_args()

background_image = None
if args.background is not None:
    background_image = read_background_image(args.background)

with dai.Device() as device, \
      pyvirtualcam.Camera(width=640, height=360, fps=30) as vcam:
    pipeline = create_pipeline()
    device.startPipeline(pipeline)

    q_color = device.getOutputQueue(name="cam", maxSize=1, blocking=False)
    q_disp = device.getOutputQueue(name="disparity", maxSize=1, blocking=False)

    while True:
      frame = resize(q_color.get().getCvFrame())
      mask = to_mask(to_grayscale(resize(q_disp.get().getFrame())))
      foreground = apply_mask(frame, mask)
      background = apply_mask(get_background(frame), 1.0 - mask)
      composite_image = foreground + background
      if params.mirror:
          composite_image = cv2.flip(composite_image, 1)
      cv2.imshow("Preview", composite_image)

      vcam_img = to_vcam_image(composite_image)
      vcam.send(vcam_img)

      key = cv2.waitKey(1)
      if key == ord('q') or cv2.getWindowProperty('Preview', cv2.WND_PROP_AUTOSIZE) == -1:
          break

      params.edit(key)

cv2.destroyAllWindows()
