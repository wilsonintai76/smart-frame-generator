from commands.FrameGeneratorCommand import entry as FrameGeneratorCommand
from commands.FrameJointCommand     import entry as FrameJointCommand

commands = [
    FrameGeneratorCommand,
    FrameJointCommand,
]

def start():
    for command in commands:
        command.start()

def stop():
    for command in commands:
        command.stop()