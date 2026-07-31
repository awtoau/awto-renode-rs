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

    /// <summary>Machine plumbing the peripherals sit on.</summary>
    public static readonly string[] Infrastructure =
    {
        "Main/Peripherals/BasicDoubleWordPeripheral.cs",
        "Main/Peripherals/BasicBytePeripheral.cs",
        "Main/Peripherals/IPeripheral.cs",
        "Main/Peripherals/Memory/MappedMemory.cs",
        "Main/Peripherals/Miscellaneous/CombinedInput.cs",
        "Main/Core/GPIO.cs",
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
