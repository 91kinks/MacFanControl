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