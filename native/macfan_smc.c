/*
 * macfan_smc.c
 * MacFanControl - Lightweight SMC helper for MacBookPro11,5
 *
 * Wraps the smcFanControl smc.c library with a simple command interface
 * designed to be called from Python via subprocess.
 *
 * Usage:
 *   ./macfan_smc temps    - dump all temperature keys (SP78 format)
 *   ./macfan_smc fans     - dump all fan info (RPM, min, max, mode)
 *
 * Build:
 *   make (see Makefile)
 *
 * All SMC access is isolated here. Python never touches IOKit directly.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Pull in the full smcFanControl implementation.
 * CMD_TOOL_BUILD enables the command-line functions (smc_init, smc_close,
 * SMCReadKey, SMCWriteKey, SMCPrintFans, SMCPrintTemps, etc.)
 * We define it here before including so smc.c compiles those sections in. */
#define CMD_TOOL_BUILD

#include "smc.h"

/* smc.c is #included directly so we compile as a single translation unit.
 * This avoids needing a separate smc.o and keeps the Makefile simple. */
#include "smc.c"

/* -------------------------------------------------------------------------
 * temps command
 *
 * Dumps every temperature key the SMC exposes.
 * Output format (one key per line):
 *   KEYNAME VALUE_CELSIUS
 *
 * Example:
 *   TC0P 52.50
 *   TGDD 68.25
 *   TG0D 67.75
 *
 * Python parses this to find the GPU and CPU keys.
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

        /* Temperature keys all start with 'T' */
        if (key[0] != 'T')
            continue;

        result = SMCReadKey(key, &val);
        if (result != kIOReturnSuccess)
            continue;

        /* SP78 is the standard temperature encoding used by Apple SMC:
         * signed fixed-point, 7 integer bits + 8 fractional bits.
         * Value = raw_int16 / 256.0 */
        if (strcmp(val.dataType, DATATYPE_SP78) == 0 && val.dataSize == 2)
        {
            float celsius = ((SInt16)ntohs(*(UInt16*)val.bytes)) / 256.0f;

            /* Skip keys that read as 0 or negative - likely unpopulated sensors */
            if (celsius <= 0.0f)
                continue;

            printf("%s %.2f\n", val.key, celsius);
        }
    }
}

/* -------------------------------------------------------------------------
 * fans command
 *
 * Dumps all fan info the SMC exposes.
 * Output format (one field per line, prefixed with fan index):
 *
 *   FAN 0
 *   ID Left Fan
 *   ACTUAL 2001
 *   MIN 1299
 *   MAX 6199
 *   SAFE 1299
 *   TARGET 2001
 *   MODE auto
 *   FAN 1
 *   ...
 *
 * Python parses this line by line.
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

        /* Fan ID / label */
        sprintf(key, "F%cID", fannum[i]);
        result = SMCReadKey(key, &val);
        if (result == kIOReturnSuccess && val.dataSize > 4)
            printf("ID %s\n", val.bytes + 4);
        else
            printf("ID unknown\n");

        /* Actual (current) speed */
        sprintf(key, "F%cAc", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("ACTUAL %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        /* Minimum speed */
        sprintf(key, "F%cMn", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("MIN %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        /* Maximum speed */
        sprintf(key, "F%cMx", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("MAX %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        /* Safe speed */
        sprintf(key, "F%cSf", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("SAFE %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        /* Target speed */
        sprintf(key, "F%cTg", fannum[i]);
        result = SMCReadKey(key, &val);
        printf("TARGET %.0f\n", (result == kIOReturnSuccess) ? getFloatFromVal(val) : -1.0f);

        /* Mode: auto vs forced
         * FS!  is a bitmask: bit N = 1 means fan N is in forced mode.
         * Fall back to per-fan FNMd key if FS! is unavailable. */
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
 * Entry point
 * ------------------------------------------------------------------------- */
int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        fprintf(stderr, "macfan_smc - MacFanControl SMC helper\n");
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s temps   - list all temperature sensors\n", argv[0]);
        fprintf(stderr, "  %s fans    - list all fan info\n", argv[0]);
        return 1;
    }

    smc_init();

    if (strcmp(argv[1], "temps") == 0)
        cmd_temps();
    else if (strcmp(argv[1], "fans") == 0)
        cmd_fans();
    else
    {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        smc_close();
        return 1;
    }

    smc_close();
    return 0;
}