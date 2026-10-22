// Only the statically qualified selector differs from the shared word control.
#define LAB_WORD_LOW 0x1000
#define LAB_WORD_HIGH 0xf541
#define LAB_FIELD_MASK 3
#define LAB_REJECT_BIT 4
#define LAB_DRIFT_LOW 0xb580
#define LAB_DRIFT_HIGH 0xb9
#include "../config_rmw/control.S"
