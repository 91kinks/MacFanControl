/*
 * macfan_smc.c
 * MacFanControl - Lightweight SMC helper for MacBookPro11,5
 *
 * Usage:
 *   ./macfan_smc temps    - dump all temperature keys
 *   ./macfan_smc fans     - dump all fan info (RPM, min, max, mode)
 */

/* Define before any includes so smc.h and smc.c both see it */
#undef  CMD_TOOL_BUILD
#define CMD_TOOL_BUILD
#define MACFAN_EMBEDDED

#include <unistd.h>


/* smc.c includes smc.h itself, and smc.h includes IOKit/IOKitLib.h.
 * Including smc.c here compiles everything as one translation unit.
 * Do NOT include smc.h separately - the header guard would cause
 * the types to be defined after our functions see them. */
#include "smc.c"

/* -------------------------------------------------------------------------
 * temps command
 *
 * Output format (one line per key):
 *   KEYNAME VALUE_CELSIUS
 * Example:
 *   TC0P 52.25
 *   TGDD 68.00
 * ------------------------------------------------------------------------- */
static void cmd_temps(void)
{
    kern_return_t result;
    SMCKeyData_t  inputStructure;
    SMCKeyData_t  outputStructure;
    int           totalKeys, i;
    UInt32Char_t  key;
    SMCVal_t      val;

    totalKeys = SMCReadIndexCount();

    for (i = 0; i < totalKeys; i++)
    {
        memset(&inputStructure,  0, sizeof(SMCKeyData_t));
        memset(&outputStructure, 0, sizeof(SMCKeyData_t));
        memset(&val,             0, sizeof(SMCVal_t));

        inputStructure.data8  = SMC_CMD_READ_INDEX;
        inputStructure.data32 = i;

        result = SMCCall(KERNEL_INDEX_SMC, &inputStructure, &outputStructure);
        if (result != kIOReturnSuccess)
            continue;

        _ultostr(key, outputStructure.key);

        if (key[0] != 'T')
            continue;

        result = SMCReadKey(key, &val);
        if (result != kIOReturnSuccess)
            continue;

        if (strcmp(val.dataType, DATATYPE_SP78) == 0 && val.dataSize == 2)
        {
            float celsius = ((SInt16)ntohs(*(UInt16*)val.bytes)) / 256.0f;
            if (celsius <= 0.0f)
                continue;
            printf("%s %.2f\n", val.key, celsius);
        }
    }
}

/* -------------------------------------------------------------------------
 * fans command
 *
 * Output format:
 *   FAN 0
 *   ID Left Fan
 *   ACTUAL 2001
 *   MIN 1299
 *   MAX 6199
 *   SAFE 1299
 *   TARGET 2001
 *   MODE auto
 * ------------------------------------------------------------------------- */
static void cmd_fans(void)
{
    kern_return_t result;
    SMCVal_t      val;
    UInt32Char_t  key;
    int           totalFans, i;

    result = SMCReadKey("FNum", &val);
    if (result != kIOReturnSuccess)
    {
        fprintf(stderr, "ERROR: could not read fan count from SMC\n");
        return;
    }

    totalFans = _strtoul((char *)val.bytes, val.dataSize, 10);

    for (i = 0; i < totalFans; i++)
    {
        printf("FAN %d\n", i);

        sprintf(key, "F%cID", fannum[i]);
        result = SMCReadKey(key, &val);
        if (result == kIOReturnSuccess && val.dataSize > 4)
            printf("ID %s\n", val.bytes + 4);
        else
            printf("ID unknown\n");

        sprintf(key, "F%cAc", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("ACTUAL %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        sprintf(key, "F%cMn", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("MIN %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        sprintf(key, "F%cMx", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("MAX %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        sprintf(key, "F%cSf", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("SAFE %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        sprintf(key, "F%cTg", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("TARGET %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        SMCReadKey("FS! ", &val);
        if (val.dataSize > 0)
        {
            int forced = (_strtoul((char *)val.bytes, 2, 16) & (1 << i)) != 0;
            printf("MODE %s\n", forced ? "forced" : "auto");
        }
        else
        {
            sprintf(key, "F%dMd", i);
            SMCReadKey(key, &val);
            printf("MODE %s\n", getFloatFromVal(val) ? "forced" : "auto");
        }
    }
}

/* -------------------------------------------------------------------------
 * write_fpe2
 *
 * Encodes an RPM value as fpe2 fixed-point and writes it to the given key.
 * fpe2 format: value = raw_uint16 / 4.0
 * So to write:  raw = (UInt16)(rpm * 4), stored big-endian.
 * ------------------------------------------------------------------------- */
static kern_return_t write_fpe2(UInt32Char_t key, int rpm)
{
    SMCVal_t val;
    UInt16   raw;

    memset(&val, 0, sizeof(SMCVal_t));
    sprintf(val.key, "%s", key);

    raw = (UInt16)(rpm * 4);

    /* Big-endian: high byte first */
    val.bytes[0] = (raw >> 8) & 0xFF;
    val.bytes[1] =  raw       & 0xFF;
    val.dataSize = 2;

    return SMCWriteKey(val);
}

/* -------------------------------------------------------------------------
 * set_forced_mode
 *
 * FS!  is a 2-byte bitmask. Bit 0 = fan 0 forced, bit 1 = fan 1 forced.
 * Pass bitmask=0x0003 to force both fans.
 * Pass bitmask=0x0000 to return both fans to auto.
 * ------------------------------------------------------------------------- */
static kern_return_t set_forced_mode(UInt16 bitmask)
{
    SMCVal_t val;

    memset(&val, 0, sizeof(SMCVal_t));
    sprintf(val.key, "FS! ");

    val.bytes[0] = (bitmask >> 8) & 0xFF;
    val.bytes[1] =  bitmask       & 0xFF;
    val.dataSize = 2;

    return SMCWriteKey(val);
}

/* -------------------------------------------------------------------------
 * cmd_set_rpm
 *
 * Sets both fans to a fixed RPM in forced mode.
 * Clamps to each fan's min/max read live from the SMC.
 * ------------------------------------------------------------------------- */
static void cmd_set_rpm(int rpm)
{
    kern_return_t result;
    SMCVal_t      val;
    UInt32Char_t  key;
    int           min0, max0, min1, max1;

    /* Read fan limits so we can clamp safely */
    sprintf(key, "F%cMn", fannum[0]);
    SMCReadKey(key, &val);
    min0 = (int)getFloatFromVal(val);

    sprintf(key, "F%cMx", fannum[0]);
    SMCReadKey(key, &val);
    max0 = (int)getFloatFromVal(val);

    sprintf(key, "F%cMn", fannum[1]);
    SMCReadKey(key, &val);
    min1 = (int)getFloatFromVal(val);

    sprintf(key, "F%cMx", fannum[1]);
    SMCReadKey(key, &val);
    max1 = (int)getFloatFromVal(val);

    /* Clamp requested RPM to valid range for each fan */
    int target0 = rpm < min0 ? min0 : (rpm > max0 ? max0 : rpm);
    int target1 = rpm < min1 ? min1 : (rpm > max1 ? max1 : rpm);

    printf("Fan limits:  Fan0 %d-%d RPM  Fan1 %d-%d RPM\n",
           min0, max0, min1, max1);
    printf("Requesting:  %d RPM\n", rpm);
    printf("Targets:     Fan0 %d RPM  Fan1 %d RPM\n", target0, target1);

    /* Step 1: enable forced mode for both fans (bitmask 0x0003) */
    result = set_forced_mode(0x0003);
    if (result != kIOReturnSuccess)
    {
        fprintf(stderr, "ERROR: could not set forced mode (FS! ) = %08x\n", result);
        return;
    }
    printf("Forced mode: enabled\n");

    /* Step 2: write target RPM to both fans */
    sprintf(key, "F%cTg", fannum[0]);
    result = write_fpe2(key, target0);
    if (result != kIOReturnSuccess)
        fprintf(stderr, "ERROR: could not write Fan0 target = %08x\n", result);
    else
        printf("Fan0 target: set to %d RPM\n", target0);

    sprintf(key, "F%cTg", fannum[1]);
    result = write_fpe2(key, target1);
    if (result != kIOReturnSuccess)
        fprintf(stderr, "ERROR: could not write Fan1 target = %08x\n", result);
    else
        printf("Fan1 target: set to %d RPM\n", target1);
}

/* -------------------------------------------------------------------------
 * cmd_set_auto
 *
 * Clears the forced mode bitmask, returning both fans to Apple auto control.
 * ------------------------------------------------------------------------- */
static void cmd_set_auto(void)
{
    kern_return_t result;

    result = set_forced_mode(0x0000);
    if (result != kIOReturnSuccess)
    {
        fprintf(stderr, "ERROR: could not clear forced mode = %08x\n", result);
        return;
    }
    printf("Forced mode: cleared\n");
    printf("Both fans:   returned to auto control\n");
}

/* -------------------------------------------------------------------------
 * Entry point
 * ------------------------------------------------------------------------- */
int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        fprintf(stderr, "macfan_smc - MacFanControl SMC helper\n");
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s temps        - list all temperature sensors\n", argv[0]);
        fprintf(stderr, "  %s fans         - list all fan info\n", argv[0]);
        fprintf(stderr, "  %s set-rpm <n>  - set both fans to n RPM\n", argv[0]);
        fprintf(stderr, "  %s set-auto     - return fans to auto control\n", argv[0]);
        return 1;
    }

    smc_init();

    if (strcmp(argv[1], "temps") == 0)
        cmd_temps();
    else if (strcmp(argv[1], "fans") == 0)
        cmd_fans();
    else if (strcmp(argv[1], "set-rpm") == 0)
    {
        if (argc < 3)
        {
            fprintf(stderr, "ERROR: set-rpm requires an RPM value\n");
            fprintf(stderr, "  Example: %s set-rpm 3000\n", argv[0]);
            smc_close();
            return 1;
        }
        int rpm = atoi(argv[2]);
        if (rpm < 1000 || rpm > 7000)
        {
            fprintf(stderr, "ERROR: RPM value %d is out of safe range (1000-7000)\n", rpm);
            smc_close();
            return 1;
        }
        cmd_set_rpm(rpm);
    }
    else if (strcmp(argv[1], "set-auto") == 0)
        cmd_set_auto();
    else
    {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        smc_close();
        return 1;
    }

    smc_close();
    return 0;
}