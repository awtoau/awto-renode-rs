namespace RenodeIngest;

/// <summary>
/// Which of Renode's ~1,968 source files are in corpus.
///
/// The cut is ARM/STM32F427 only. Everything else -- other architectures, the
/// monitor, .repl/.resc parsing, the GUI, plugins, save/restore -- is out, and
/// tlib is C so it is not a candidate at all.
///
/// Selection is by explicit path suffix rather than by glob over directories,
/// because "everything under Peripherals/" would pull in 854 files when we need
/// about 22. Being wrong here is cheap to fix and expensive not to notice, so
/// the ingest reports any entry it could not resolve.
/// </summary>
public static class CorpusCut
{
    /// <summary>Peripherals instantiated by the F427 platform description.</summary>
    public static readonly string[] Peripherals =
    {
        "Peripherals/Peripherals/UART/STM32_UART.cs",
        "Peripherals/Peripherals/CAN/STMCAN.cs",
        "Peripherals/Peripherals/Timers/STM32_Timer.cs",
        "Peripherals/Peripherals/Timers/STM32F4_RTC.cs",
        "Peripherals/Peripherals/Timers/STM32_IndependentWatchdog.cs",
        "Peripherals/Peripherals/DMA/STM32DMA.cs",
        "Peripherals/Peripherals/SPI/STM32SPI.cs",
        "Peripherals/Peripherals/I2C/STM32F1_I2C.cs",
        "Peripherals/Peripherals/Analog/STM32_ADC.cs",
        "Peripherals/Peripherals/CRC/STM32_CRC.cs",
        "Peripherals/Peripherals/GPIOPort/STM32_GPIOPort.cs",
        "Peripherals/Peripherals/MTD/STM32F4_FlashController.cs",
        "Peripherals/Peripherals/IRQControllers/STM32F4_EXTI.cs",
        "Peripherals/Peripherals/Miscellaneous/STM32F4_RCC.cs",
        "Peripherals/Peripherals/Miscellaneous/STM32_PWR.cs",
        "Peripherals/Peripherals/Miscellaneous/STM32_RNG.cs",
        "Peripherals/Peripherals/Miscellaneous/STM32_SYSCFG.cs",
        "Peripherals/Peripherals/Miscellaneous/BitBanding.cs",
    };

    /// <summary>ARM Cortex-M core bindings. These are C#; tlib beneath them is C.</summary>
    public static readonly string[] CoreBindings =
    {
        "Cores/Arm-M/NVIC.cs",
        "Cores/Arm-M/CortexM.cs",
    };

    /// <summary>
    /// The register DSL -- 20 combinators, and the single highest-leverage
    /// translation in the project.
    /// </summary>
    public static readonly string[] RegisterDsl =
    {
        "Main/Core/Structure/Registers/PeripheralRegister.cs",
        "Main/Core/Structure/Registers/PeripheralRegisterExtensions.cs",
        "Main/Core/Structure/Registers/RegisterCollection.cs",
        "Main/Core/Structure/Registers/RegisterField.cs",
        "Main/Core/Structure/Registers/RegisterSelector.cs",
        "Main/Core/Structure/Registers/FieldMode.cs",
        "Main/Core/Structure/Registers/IFlagRegisterField.cs",
        "Main/Core/Structure/Registers/IValueRegisterField.cs",
        "Main/Core/Structure/Registers/IEnumRegisterField.cs",
        "Main/Core/Structure/Registers/Tag.cs",
    };

    /// <summary>
    /// Machine plumbing the peripherals sit on.
    ///
    /// The second group was NOT chosen by reading the platform description --
    /// it came from querying the ingested call graph for what the cut actually
    /// calls outside itself. Guessing the cut is how you discover a missing
    /// dependency three phases later.
    /// </summary>
    public static readonly string[] Infrastructure =
    {
        "Main/Peripherals/BasicDoubleWordPeripheral.cs",
        "Main/Peripherals/BasicBytePeripheral.cs",
        // Base classes of peripherals already in the cut. Omitting a base is
        // the same omission as omitting a called method: the derived type
        // cannot be translated without it, since Rust has no inheritance and
        // the base is flattened into the derived peripheral.
        "Main/Peripherals/GPIOPort/BaseGPIOPort.cs", // base of STM32_GPIOPort
        // The scheduling primitives peripherals reach through IMachine. We had
        // the INTERFACE and not the implementation, which made a missing
        // dependency look like an open design question -- twice.
        //
        // Deliberately NOT Machine.cs: it is 2,271 lines and the hub of the
        // emulator, referencing LocalTimeSource, SystemBus and EmulationManager,
        // which PLAN.md sizes at ~6,277 and ~9,832 lines. These three are 535
        // lines and self-contained -- BaseClockSource refers only to
        // TimeInterval, ClockEntry and its own members. The converter's
        // withholding will name whatever else is genuinely required, rather
        // than us guessing and importing the whole emulator to find out.
        "Main/Time/TimeInterval.cs",      // ScheduleAction's delay type
        "Main/Time/ClockEntry.cs",        // one queue entry
        "Main/Time/BaseClockSource.cs",   // the queue itself
        // The bus interface peripherals reach through IMachine.GetSystemBus --
        // the single most-called member of IMachine in this corpus (9 sites),
        // and the last type the converter reported as outside the cut.
        "Main/Peripherals/Bus/IBusController.cs",
        "Main/Peripherals/UART/IUART.cs",            // Parity/Bits, returned by STM32_UART
        "Main/Peripherals/IPeripheral.cs",
        "Main/Peripherals/IMachine.cs",
        "Main/Peripherals/Memory/MappedMemory.cs",
        "Main/Peripherals/Miscellaneous/CombinedInput.cs",
        "Main/Core/GPIO.cs",
        // Found by call-graph query, with the call counts that justified each:
        "Main/Core/IGPIO.cs",                       // IGPIOExtensions Set/Unset, 45
        "Main/Logging/Logger.cs",                   // Log/NoisyLog/Warning/Debug, 180
        "Main/Exceptions/ConstructionException.cs", // 19
        "Main/Exceptions/RecoverableException.cs",  // 17
        "Main/Utilities/BitHelper.cs",              // GetValue/AreAnyBitsSet, 20+
        "Main/Utilities/Misc.cs",                   // FormatWith and friends, 12+
    };

    public static IEnumerable<string> All() =>
        Peripherals.Concat(CoreBindings).Concat(RegisterDsl).Concat(Infrastructure);

    /// <summary>
    /// True when a document path is in corpus. Matching is on a normalised
    /// suffix so nothing here depends on where the Renode tree lives.
    /// </summary>
    public static bool Contains(string documentPath)
    {
        var norm = documentPath.Replace('\\', '/');
        return All().Any(s => norm.EndsWith(s, StringComparison.Ordinal));
    }
}
