#include <Servo.h>

int push = 7;
Servo servo_end, servo_middle, servo_base;

int pose_base = 0;
int pose_middle = 0;
int pose_end = 0;

int state = 0;

unsigned long lastUpdate = 0;
const int STEP_DELAY = 80;

void setup() {
  pinMode(push, INPUT_PULLUP);

  servo_end.attach(6);
  servo_middle.attach(5);
  servo_base.attach(3);

  servo_end.write(0);
  servo_middle.write(0);
  servo_base.write(0);
}

void loop() {

  // Trigger
  if (digitalRead(push) == LOW && state == 0) {
    state = 1;

    pose_base = 0;
    pose_middle = 0;
    pose_end = 0;

    lastUpdate = millis();
  }

  // Timing control
  if (millis() - lastUpdate < STEP_DELAY) return;
  lastUpdate = millis();

  switch (state) {

    // EXTENSION PHASE

    case 1: // Middle extend partial
      if (pose_middle < 60) {
        servo_middle.write(pose_middle++);
      } else {
        state = 2;
      }
      break;

    case 2: // Base extend
      if (pose_base < 140) {
        servo_base.write(pose_base++);
      } else {
        state = 3;
      }
      break;

    case 3: // Middle extend full
      if (pose_middle < 120) {
        servo_middle.write(pose_middle++);
      } else {
        state = 4;
      }
      break;


    case 4: // End (bucket scoop)
      if (pose_end < 120) {
        servo_end.write(pose_end++);
      } else {
        state = 5;
      }
      break;


    // RETRACTION PHASE

    case 5: // middle retract partial
      if (pose_middle > 60) {
        servo_middle.write(pose_middle--);
      } else {
        state = 6;
      }
      break;

    case 6: // Base retract
      if (pose_base > 0) {
        servo_base.write(pose_base--);
      } else {
        state = 7; // done
      }
      break;

    case 7: // Middle retract
      if (pose_middle > 0) {
        servo_middle.write(pose_middle--);
      } else {
        state = 8;
      }
      break;


  }
}