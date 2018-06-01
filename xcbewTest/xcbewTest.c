#include <stdlib.h>
#include <stdio.h>
#include "xcbew.h"
#include <string.h>

int main(int argc, char* argv[]) {
  (void) argc;  // Ignored.
  (void) argv;  // Ignored.
  if (xcbewInit() == XCBEW_SUCCESS) {
    printf("XCB found\n");
  }
  else {
    printf("XCB not found\n");
  }
  return EXIT_SUCCESS;
}
