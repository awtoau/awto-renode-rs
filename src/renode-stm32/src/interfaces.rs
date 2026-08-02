//! C# interfaces as Rust traits, GENERATED from the corpus.
//!
//! Do not edit: `scripts/check_generated.py` fails the commit if this
//! file differs from converter output. To change it, change the rules
//! in `rulesdb/rules/` or the C# it is derived from.
//!
//! A trait here is COMPLETE: every member the C# interface declares,
//! and every interface it inherits. One that cannot be complete is
//! withheld whole and listed below -- a trait missing members would
//! carry a name it does not live up to.
//!
//! WITHHELD, with the count of members that cannot be expressed:
//!   - Antmicro.Renode.Backends.Display.IDisplay: 3 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- overload, type_without_definition
//!   - Antmicro.Renode.Backends.Display.IPixelBlender: 5 of 5 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Backends.Display.IPixelConverter: 3 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Config.IJsonSerializerStrategy: 2 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- bcl_unmapped, type_not_in_corpus
//!   - Antmicro.Renode.Core.IConnectable: 0 of 0 member(s) and 0 of 0 inherited interface(s) blocked -- name_collision
//!   - Antmicro.Renode.Core.IConnectable<T>: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Core.IGPIO: 2 of 8 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Core.IGPIOWithHooks: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.IHasPreservableState: 2 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Core.IMachine: 49 of 92 member(s) and 0 of 3 inherited interface(s) blocked -- bcl_unmapped, generic_method, interface_withheld, overload, property_without_accessor, type_without_definition
//!   - Antmicro.Renode.Core.IManagedThread: 0 of 3 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.IMassConnectable<T>: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.INetworkLogSwitch: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- type_argument_without_value_form
//!   - Antmicro.Renode.Core.INetworkLogWireless: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- type_argument_without_value_form
//!   - Antmicro.Renode.Core.INumberedGPIOOutput: 1 of 1 member(s) and 0 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.IPeripheralsGroup: 1 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.IPeripheralsGroupsManager: 5 of 5 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Core.IReadOnlyMinimalRangesCollection: 2 of 3 member(s) and 1 of 1 inherited interface(s) blocked -- type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Core.ISimpleManagedThread: 1 of 3 member(s) and 1 of 1 inherited interface(s) blocked -- type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Core.Structure.IBusRegistration: 2 of 5 member(s) and 0 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Core.Structure.IConditionalRegistration: 1 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Core.Structure.IJsonSerializable: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Core.Structure.Registers.IRegisterCollection: 0 of 6 member(s) and 0 of 0 inherited interface(s) blocked -- name_collision
//!   - Antmicro.Renode.Core.Structure.Registers.IRegisterCollection<T>: 0 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Core.SymbolLookup.SortedIntervals.ISymbolProvider: 2 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Core.USB.IProvidesDescriptor: 1 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Core.USB.IUSBDevice: 1 of 1 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.EventRecording.IRecordEntry: 2 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- bcl_unmapped, type_without_definition
//!   - Antmicro.Renode.Extensions.Analyzers.Video.Events.IEventSource: 1 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.HostInterfaces.Network.IHostNetworkInterface: 0 of 0 member(s) and 2 of 4 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.HostInterfaces.Network.ITapInterface: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Logging.ILogger: 2 of 8 member(s) and 1 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Logging.ILoggerBackend: 4 of 7 member(s) and 1 of 1 inherited interface(s) blocked -- type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Network.IBasicNetworkNode<TData, TAddress>: 1 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Bus.IBusController: 41 of 70 member(s) and 8 of 10 inherited interface(s) blocked -- bcl_unmapped, generic_method, interface_withheld, overload, type_argument_without_value_form, type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Peripherals.Bus.IBusRegistered<T>: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- type_argument_without_value_form
//!   - Antmicro.Renode.Peripherals.Bus.IGaislerAHB: 1 of 4 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Bus.IGaislerAPB: 1 of 4 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Bus.SystemBus.IReadOnlyPeripheralCollection: 2 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.Bus.Wrappers.PeripheralAccessProfiler.IAccessProfilerWrapper: 2 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CAN.ICAN: 2 of 2 member(s) and 0 of 2 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.CAN.S32K3XX_FlexCAN.ILegacyRxFifoMatcher: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.CFU.ICFU: 2 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.Disassembler.IFlaglessDisassembler: 1 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.IARMCPUsConnectionsProvider: 3 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.IARMSingleSecurityStateCPU: 3 of 5 member(s) and 1 of 2 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.IARMTwoSecurityStatesCPU: 2 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.IArmWithSystemRegisters: 4 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICPU: 10 of 20 member(s) and 0 of 4 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICPUSupportingLLVMDisas: 1 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithDirtyAdressesSharing: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithExternalMmu: 5 of 19 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithHooks: 3 of 8 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithMMU: 2 of 3 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithMappedMemory: 2 of 7 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithMemoryAccessHooks: 1 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithMetrics: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithNMI: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithPSCI: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithPostGprAccessHooks: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.ICPUWithRegisters: 3 of 3 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.IControllableCPU: 1 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.ICpuSupportingGdb: 2 of 7 member(s) and 2 of 2 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.CPU.IInitableCPU: 2 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.CPU.ISignalsUnit: 2 of 8 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.CPU.Registers.IRegisters: 3 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- property_without_accessor, type_without_definition
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcBlockBytePeripheral: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcBytePeripheral: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcDoubleWordPeripheral: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcPeripheral: 2 of 2 member(s) and 1 of 2 inherited interface(s) blocked -- type_argument_without_value_form, type_without_definition
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcQuadWordPeripheral: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.DMA.ISamPdcWordPeripheral: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.IAnalyzableBackend: 0 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- name_collision
//!   - Antmicro.Renode.Peripherals.IAnalyzableBackend<T>: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.IAnalyzableBackendAnalyzer: 1 of 4 member(s) and 0 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.IAnalyzableBackendAnalyzer<T>: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.ICluster<T>: 1 of 2 member(s) and 1 of 2 inherited interface(s) blocked -- interface_withheld, type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.IEndiannessAware: 1 of 1 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.IHasDelayedInvalidationContext: 1 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.IPhysicalLayer: 0 of 0 member(s) and 0 of 1 inherited interface(s) blocked -- name_collision
//!   - Antmicro.Renode.Peripherals.IPhysicalLayer<T, V>: 0 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.IPhysicalLayer<T>: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.IRQControllers.IAPICPeripheral: 1 of 1 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.IRQControllers.PLIC.IPlatformLevelInterruptController: 1 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.Input.IAbsolutePositionPointerInput: 0 of 5 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.Input.IKeyboard: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Input.IPointerInput: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Input.IRelativePositionPointerInput: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.Miscellaneous.IOpenTitan_BigNumberAcceleratorCore: 4 of 11 member(s) and 0 of 0 inherited interface(s) blocked -- bcl_unmapped, type_without_definition
//!   - Antmicro.Renode.Peripherals.Miscellaneous.S32K3XX_FlexIOModel.IEndpoint: 1 of 1 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Miscellaneous.S32K3XX_FlexIOModel.IResourceBlockOwner: 0 of 0 member(s) and 1 of 2 inherited interface(s) blocked -- type_argument_without_value_form
//!   - Antmicro.Renode.Peripherals.Miscellaneous.SiLabs.IHFXO_EFR32xG2: 1 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Network.IEmulatedNetworkService: 0 of 7 member(s) and 1 of 2 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Network.IMACInterface: 4 of 4 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Network.SynopsysDWCEthernetQualityOfService.Descriptor.IDescriptorStruct: 1 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.PCI.IPCIPeripheral: 1 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.PCI.IPCIeRouter: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.SENT.ISENTPeripheral: 1 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.SPI.Cadence_xSPICommands.IDMACommand: 1 of 6 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Sensor.IADC: 6 of 9 member(s) and 1 of 2 inherited interface(s) blocked -- property_without_accessor, type_argument_without_value_form, type_without_definition
//!   - Antmicro.Renode.Peripherals.Sensor.IHumiditySensor: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Sensor.IIlluminanceSensor: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Sensor.IPressureSensor: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Sensor.ITemperatureSensor: 2 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Peripherals.Timers.EFR32_RTCCCounter.ICCChannel: 4 of 7 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.UART.IDelayableUART: 1 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.UART.ILINController: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.UART.ILINDevice: 0 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.UART.IUART: 0 of 0 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.UART.IUART<T>: 2 of 5 member(s) and 0 of 1 inherited interface(s) blocked -- name_collision, type_without_definition
//!   - Antmicro.Renode.Peripherals.UART.IUARTWithBufferState: 2 of 2 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.Peripherals.UART.IUARTWithFrameInfo: 0 of 0 member(s) and 2 of 2 inherited interface(s) blocked -- interface_withheld, name_collision
//!   - Antmicro.Renode.Peripherals.UART.IUARTWithFrameInfo<T>: 1 of 1 member(s) and 1 of 1 inherited interface(s) blocked -- interface_withheld, name_collision, type_without_definition
//!   - Antmicro.Renode.Peripherals.USBDeprecated.IUSBHub: 2 of 4 member(s) and 2 of 2 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Peripherals.USBDeprecated.IUSBHubBase: 2 of 4 member(s) and 2 of 2 inherited interface(s) blocked -- interface_withheld, type_argument_without_value_form
//!   - Antmicro.Renode.Peripherals.USBDeprecated.IUSBPeripheral: 18 of 28 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Video.Allegro_E310.ICommand: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Video.IVideo: 1 of 2 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus, type_without_definition
//!   - Antmicro.Renode.Peripherals.Wireless.IMediumFunction: 2 of 3 member(s) and 0 of 1 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Peripherals.Wireless.ISlipRadio: 0 of 0 member(s) and 1 of 3 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.Time.IClockSource: 8 of 10 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Time.ITimeSink: 2 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Time.ITimeSource: 5 of 8 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld, type_without_definition
//!   - Antmicro.Renode.UI.IConsoleBackendAnalyzerProvider: 1 of 4 member(s) and 0 of 1 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.UI.IHasWidget: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_not_in_corpus
//!   - Antmicro.Renode.UserInterface.IUserInterfaceProvider: 2 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Utilities.Collections.IArray<T>: 1 of 4 member(s) and 1 of 1 inherited interface(s) blocked -- property_without_accessor, type_not_in_corpus
//!   - Antmicro.Renode.Utilities.Collections.IInterval<TScalar>: 1 of 4 member(s) and 0 of 0 inherited interface(s) blocked -- interface_withheld
//!   - Antmicro.Renode.Utilities.IBlobProvider: 1 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Utilities.ICanLoadFiles: 1 of 1 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Utilities.ILINEntry: 2 of 10 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.Utilities.RESD.IDataBlock: 3 of 8 member(s) and 0 of 0 inherited interface(s) blocked -- type_without_definition
//!   - Antmicro.Renode.WebSockets.IWebSocketServerProvider: 2 of 2 member(s) and 0 of 0 inherited interface(s) blocked -- bcl_unmapped, type_without_definition
//!
//! Per-member reasons: docs/status/interfaces.md, derived by
//! scripts/interface_census.py from this same analysis.
//!
//! DEVIATION: a C# `event` is emitted as ONE subscribe method.
//! `-=` has no form -- a boxed closure has no identity to remove
//! by -- and the multicast narrowing is the one already recorded
//! in stdlib.delegates.

/// C# `Antmicro.Renode.Backends.Display.XInput.IInputHandler`, member for member.
pub trait IInputHandler {
    fn button_pressed(&mut self, button: i32) -> ();
    fn button_released(&mut self, button: i32) -> ();
    fn key_pressed(&mut self, key: i32) -> ();
    fn key_released(&mut self, key: i32) -> ();
    fn mouse_moved(&mut self, x: i32, y: i32, dx: i32, dy: i32) -> ();
    fn cursor_fixed(&mut self) -> bool;
    fn stop(&mut self) -> bool;
    fn set_stop(&mut self, value: bool) -> ();
}

/// C# `Antmicro.Renode.Core.CAN.ISocketCANFrame`, member for member.
pub trait ISocketCANFrame {
    fn size(&mut self) -> i32;
}

/// C# `Antmicro.Renode.Core.ICoalescable<T>`, member for member.
pub trait ICoalescable<T> {
    fn coalesce(&mut self, source: T) -> ();
}

/// C# `Antmicro.Renode.Core.IDisconnectableState`, member for member.
pub trait IDisconnectableState: IPreservable {
    fn disconnect_state(&mut self) -> ();
}

/// C# `Antmicro.Renode.Core.IExternal`, member for member.
pub trait IExternal: IEmulationElement {
}

/// C# `Antmicro.Renode.Core.IGPIOReceiver`, member for member.
pub trait IGPIOReceiver: IPeripheral {
    fn on_gpio(&mut self, number: i32, value: bool) -> ();
}

/// C# `Antmicro.Renode.Core.IGPIOSender`, member for member.
pub trait IGPIOSender: IPeripheral {
}

/// C# `Antmicro.Renode.Core.IHasAutomaticallyConnectedGPIOOutputs`, member for member.
pub trait IHasAutomaticallyConnectedGPIOOutputs {
    fn disconnect_automatically_connected_gpio_outputs(&mut self) -> ();
}

/// C# `Antmicro.Renode.Core.IHostMachineElement`, member for member.
pub trait IHostMachineElement: IEmulationElement {
}

/// C# `Antmicro.Renode.Core.IIdentifiable`, member for member.
pub trait IIdentifiable {
    fn unique_object_id(&mut self) -> i32;
}

/// C# `Antmicro.Renode.Core.ILocalGPIOReceiver`, member for member.
pub trait ILocalGPIOReceiver {
    fn get_local_receiver(&mut self, index: i32) -> std::rc::Rc<std::cell::RefCell<dyn IGPIOReceiver>>;
}

/// C# `Antmicro.Renode.Core.IMappedSegment`, member for member.
pub trait IMappedSegment {
    fn touch(&mut self) -> ();
    fn pointer(&mut self) -> isize;
    fn size(&mut self) -> u64;
    fn starting_offset(&mut self) -> u64;
}

/// C# `Antmicro.Renode.Core.INetworkLog<T>`, member for member.
pub trait INetworkLog<T>: IExternal {
    fn subscribe_frame_processed(&mut self, handler: Option<Box<dyn FnMut(std::rc::Rc<std::cell::RefCell<dyn IExternal>>, T, Vec<u8>)>>);
    fn subscribe_frame_transmitted(&mut self, handler: Option<Box<dyn FnMut(std::rc::Rc<std::cell::RefCell<dyn IExternal>>, T, T, Vec<u8>)>>);
}

/// C# `Antmicro.Renode.Core.IPreservable`, member for member.
pub trait IPreservable {
}

/// C# `Antmicro.Renode.Core.Structure.ICovariantRegisterablePeripheral<TPeripheral, TRegistrationPoint>`, member for member.
pub trait ICovariantRegisterablePeripheral<TPeripheral, TRegistrationPoint>: IEmulationElement {
}

/// C# `Antmicro.Renode.Core.Structure.IHasChildren<T>`, member for member.
pub trait IHasChildren<T> {
    fn get_names(&mut self) -> Vec<String>;
    fn try_get_by_name(&mut self, name: String, success: &mut bool) -> T;
}

/// C# `Antmicro.Renode.Core.Structure.IPeripheralContainer<TPeripheral, TRegistrationPoint>`, member for member.
pub trait IPeripheralContainer<TPeripheral, TRegistrationPoint>: IRegisterablePeripheral<TPeripheral, TRegistrationPoint> {
    fn get_registration_points(&mut self, peripheral: TPeripheral) -> Vec<TRegistrationPoint>;
    fn children(&mut self) -> Vec<std::rc::Rc<std::cell::RefCell<dyn IRegistered<TPeripheral, TRegistrationPoint>>>>;
}

/// C# `Antmicro.Renode.Core.Structure.IRegisterablePeripheral<TPeripheral, TRegistrationPoint>`, member for member.
pub trait IRegisterablePeripheral<TPeripheral, TRegistrationPoint>: ICovariantRegisterablePeripheral<TPeripheral, TRegistrationPoint> {
    fn register(&mut self, peripheral: TPeripheral, registration_point: TRegistrationPoint) -> ();
    fn unregister(&mut self, peripheral: TPeripheral) -> ();
}

/// C# `Antmicro.Renode.Core.Structure.IRegistered<TPeripheral, TRegistrationPoint>`, member for member.
pub trait IRegistered<TPeripheral, TRegistrationPoint> {
    fn peripheral(&mut self) -> TPeripheral;
    fn registration_point(&mut self) -> TRegistrationPoint;
}

/// C# `Antmicro.Renode.Core.Structure.IRegistrationPoint`, member for member.
pub trait IRegistrationPoint {
    fn pretty_string(&mut self) -> String;
}

/// C# `Antmicro.Renode.Core.Structure.ISimpleContainer`, member for member.
pub trait ISimpleContainer {
    fn child_collection(&mut self) -> std::collections::BTreeMap<i32, std::rc::Rc<std::cell::RefCell<dyn IPeripheral>>>;
}

/// C# `Antmicro.Renode.Core.Structure.ITheOnlyPossibleRegistrationPoint`, member for member.
pub trait ITheOnlyPossibleRegistrationPoint: IRegistrationPoint {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IEnumRegisterField<T>`, member for member.
pub trait IEnumRegisterField<T>: IRegisterField<T> {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IFlagRegisterField`, member for member.
pub trait IFlagRegisterField: IRegisterField<bool> {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IPacketRegisterField<T>`, member for member.
pub trait IPacketRegisterField<T>: IRegisterField<T> {
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IPeripheralRegister<T>`, member for member.
pub trait IPeripheralRegister<T> {
    fn dump(&mut self, allow_side_effects: bool) -> csharp_rt::Array2D<String>;
    fn read(&mut self) -> T;
    fn reset(&mut self) -> ();
    fn shadow_reload(&mut self) -> ();
    fn write(&mut self, offset: i64, value: T) -> ();
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IProvidesRegisterCollection<T>`, member for member.
pub trait IProvidesRegisterCollection<T> {
    fn registers_collection(&mut self) -> T;
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IRegisterField<T>`, member for member.
pub trait IRegisterField<T> {
    fn change_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn read_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn shadow_reload_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn shadow_value(&mut self) -> T;
    fn value(&mut self) -> T;
    fn value_provider_callback(&mut self) -> Option<Box<dyn FnMut(T) -> T>>;
    fn width(&mut self) -> i32;
    fn write_callback(&mut self) -> Option<Box<dyn FnMut(T, T)>>;
    fn set_change_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_read_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_shadow_reload_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
    fn set_shadow_value(&mut self, value: T) -> ();
    fn set_value(&mut self, value: T) -> ();
    fn set_value_provider_callback(&mut self, value: Option<Box<dyn FnMut(T) -> T>>) -> ();
    fn set_write_callback(&mut self, value: Option<Box<dyn FnMut(T, T)>>) -> ();
}

/// C# `Antmicro.Renode.Core.Structure.Registers.IValueRegisterField`, member for member.
pub trait IValueRegisterField: IRegisterField<u64> {
}

/// C# `Antmicro.Renode.IEmulationElement`, member for member.
pub trait IEmulationElement {
}

/// C# `Antmicro.Renode.Peripherals.ATAPI.IAtapiPeripheral`, member for member.
pub trait IAtapiPeripheral: IPeripheral {
    fn dequeue_data(&mut self) -> u16;
    fn handle_command(&mut self, packet: Vec<u8>) -> ();
    fn send_identify_response(&mut self) -> ();
    fn data_ready(&mut self) -> bool;
}

/// C# `Antmicro.Renode.Peripherals.Bus.IBusPeripheral`, member for member.
pub trait IBusPeripheral: IPeripheral {
}

/// C# `Antmicro.Renode.Peripherals.Bus.IBytePeripheral`, member for member.
pub trait IBytePeripheral: IBusPeripheral {
    fn read_byte(&mut self, offset: i64) -> u8;
    fn write_byte(&mut self, offset: i64, value: u8) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Bus.IDoubleWordPeripheral`, member for member.
pub trait IDoubleWordPeripheral: IBusPeripheral {
    fn read_double_word(&mut self, offset: i64) -> u32;
    fn write_double_word(&mut self, offset: i64, value: u32) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Bus.IMultibyteWritePeripheral`, member for member.
pub trait IMultibyteWritePeripheral {
    fn read_bytes(&mut self, offset: i64, count: i32, context: std::rc::Rc<std::cell::RefCell<dyn IPeripheral>>) -> Vec<u8>;
    fn write_bytes(&mut self, offset: i64, array: Vec<u8>, starting_index: i32, count: i32, context: std::rc::Rc<std::cell::RefCell<dyn IPeripheral>>) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Bus.IQuadWordPeripheral`, member for member.
pub trait IQuadWordPeripheral: IBusPeripheral {
    fn read_quad_word(&mut self, offset: i64) -> u64;
    fn write_quad_word(&mut self, offset: i64, value: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Bus.IWordPeripheral`, member for member.
pub trait IWordPeripheral: IBusPeripheral {
    fn read_word(&mut self, offset: i64) -> u16;
    fn write_word(&mut self, offset: i64, value: u16) -> ();
}

/// C# `Antmicro.Renode.Peripherals.CAN.STM32_FDCAN.IFilterElement`, member for member.
pub trait IFilterElement {
    fn matches_id(&mut self, id: u32, xid_mask: u32) -> bool;
}

/// C# `Antmicro.Renode.Peripherals.CPU.IHaltable`, member for member.
pub trait IHaltable {
    fn is_halted(&mut self) -> bool;
    fn set_is_halted(&mut self, value: bool) -> ();
}

/// C# `Antmicro.Renode.Peripherals.CPU.IIndirectCSRPeripheral`, member for member.
pub trait IIndirectCSRPeripheral: IPeripheral {
    fn read_indirect_csr(&mut self, iselect: u32, ireg: u32) -> u32;
    fn write_indirect_csr(&mut self, iselect: u32, ireg: u32, value: u32) -> ();
}

/// C# `Antmicro.Renode.Peripherals.DMA.IDMA`, member for member.
pub trait IDMA: IPeripheral {
    fn request_transfer(&mut self, channel: i32) -> ();
    fn number_of_channels(&mut self) -> i32;
}

/// C# `Antmicro.Renode.Peripherals.I2C.II2CPeripheral`, member for member.
pub trait II2CPeripheral: IPeripheral {
    fn finish_transmission(&mut self) -> ();
    fn read(&mut self, count: i32) -> Vec<u8>;
    fn write(&mut self, data: Vec<u8>) -> ();
}

/// C# `Antmicro.Renode.Peripherals.IAbsoluteAddressAware`, member for member.
pub trait IAbsoluteAddressAware {
    fn set_absolute_address(&mut self, address: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.IAnalyzable`, member for member.
pub trait IAnalyzable: IEmulationElement {
}

/// C# `Antmicro.Renode.Peripherals.IContextState`, member for member.
pub trait IContextState {
}

/// C# `Antmicro.Renode.Peripherals.IExecutableIO`, member for member.
pub trait IExecutableIO: IMemory {
}

/// C# `Antmicro.Renode.Peripherals.IHasDivisibleFrequency`, member for member.
pub trait IHasDivisibleFrequency: IHasFrequency {
    fn divider(&mut self) -> u64;
    fn set_divider(&mut self, value: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.IHasFrequency`, member for member.
pub trait IHasFrequency {
    fn frequency(&mut self) -> u64;
    fn set_frequency(&mut self, value: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.IHasMappedRegisters`, member for member.
pub trait IHasMappedRegisters {
    fn offset_to_string(&mut self, offset: i64) -> String;
}

/// C# `Antmicro.Renode.Peripherals.IHasOwnLife`, member for member.
pub trait IHasOwnLife {
    fn pause(&mut self) -> ();
    fn resume(&mut self) -> ();
    fn start(&mut self) -> ();
    fn is_paused(&mut self) -> bool;
}

/// C# `Antmicro.Renode.Peripherals.IKnownSize`, member for member.
pub trait IKnownSize: IBusPeripheral {
    fn size(&mut self) -> i64;
}

/// C# `Antmicro.Renode.Peripherals.IMapped`, member for member.
pub trait IMapped: IBusPeripheral {
    fn mapped_segments(&mut self) -> Vec<std::rc::Rc<std::cell::RefCell<dyn IMappedSegment>>>;
}

/// C# `Antmicro.Renode.Peripherals.IMemory`, member for member.
pub trait IMemory: IBytePeripheral + IDoubleWordPeripheral + IMultibyteWritePeripheral + IQuadWordPeripheral + IWordPeripheral + IKnownSize + IPeripheral {
}

/// C# `Antmicro.Renode.Peripherals.IPeripheral`, member for member.
pub trait IPeripheral: IEmulationElement + IAnalyzable {
    fn reset(&mut self) -> ();
}

/// C# `Antmicro.Renode.Peripherals.IPeripheralWithTransactionState`, member for member.
pub trait IPeripheralWithTransactionState: IPeripheral {
    fn try_convert_state_obj_to_ulong(&mut self, state_obj: std::rc::Rc<std::cell::RefCell<dyn IContextState>>, state: &mut Option<u64>) -> bool;
    fn try_convert_ulong_to_state_obj(&mut self, state: Option<u64>, state_obj: &mut std::rc::Rc<std::cell::RefCell<dyn IContextState>>) -> bool;
    fn state_bits(&mut self) -> std::collections::BTreeMap<String, i32>;
}

/// C# `Antmicro.Renode.Peripherals.IRQControllers.IIRQController`, member for member.
pub trait IIRQController: IGPIOReceiver {
}

/// C# `Antmicro.Renode.Peripherals.Input.IInputDevice`, member for member.
pub trait IInputDevice: IPeripheral {
}

/// C# `Antmicro.Renode.Peripherals.Input.IPS2Controller`, member for member.
pub trait IPS2Controller {
    fn notify(&mut self) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Input.IPS2Peripheral`, member for member.
pub trait IPS2Peripheral: IPeripheral {
    fn read(&mut self) -> u8;
    fn write(&mut self, value: u8) -> ();
    fn controller(&mut self) -> std::rc::Rc<std::cell::RefCell<dyn IPS2Controller>>;
    fn set_controller(&mut self, value: std::rc::Rc<std::cell::RefCell<dyn IPS2Controller>>) -> ();
}

/// C# `Antmicro.Renode.Peripherals.MTD.ISPIFlash`, member for member.
pub trait ISPIFlash: IPeripheral {
    fn read_id(&mut self) -> u32;
    fn read_status_register(&mut self, register_number: u32) -> u32;
    fn write_disable(&mut self) -> ();
    fn write_enable(&mut self) -> ();
    fn write_status_register(&mut self, register_number: u32, value: u32) -> ();
}

/// C# `Antmicro.Renode.Peripherals.MemoryControllers.ISMMUv3StreamController`, member for member.
pub trait ISMMUv3StreamController {
    fn invalidate_tlb(&mut self, virtual_address: Option<u64>) -> ();
    fn enabled(&mut self) -> bool;
    fn set_enabled(&mut self, value: bool) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Miscellaneous.ILed`, member for member.
pub trait ILed: IPeripheral {
    fn subscribe_state_changed(&mut self, handler: Option<Box<dyn FnMut(std::rc::Rc<std::cell::RefCell<dyn ILed>>, bool)>>);
    fn state(&mut self) -> bool;
}

/// C# `Antmicro.Renode.Peripherals.Miscellaneous.INRFEventProvider`, member for member.
pub trait INRFEventProvider {
    fn subscribe_event_triggered(&mut self, handler: Option<Box<dyn FnMut(u32)>>);
}

/// C# `Antmicro.Renode.Peripherals.Miscellaneous.ISideloadableKey`, member for member.
pub trait ISideloadableKey {
    fn set_sideload_key(&mut self, value: Vec<u8>) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Miscellaneous.SiLabs.ICMU_EFR32xG2`, member for member.
pub trait ICMU_EFR32xG2 {
    fn osc_perpll_enabled(&mut self, instance: u32) -> bool;
    fn osc_perpll_requested(&mut self, instance: u32) -> bool;
    fn osc_socpll_enabled(&mut self, instance: u32) -> bool;
    fn osc_socpll_requested(&mut self, instance: u32) -> bool;
    fn dpll_m(&mut self) -> u64;
    fn dpll_n(&mut self) -> u64;
    fn osc_dpll_enabled(&mut self) -> bool;
    fn osc_hfrco_em23_enabled(&mut self) -> bool;
    fn osc_hfrco_em23_requested(&mut self) -> bool;
    fn osc_hfrco_enabled(&mut self) -> bool;
    fn osc_hfrco_requested(&mut self) -> bool;
    fn osc_hfxo_enabled(&mut self) -> bool;
    fn osc_hfxo_requested(&mut self) -> bool;
    fn osc_lfrco_enabled(&mut self) -> bool;
    fn osc_lfrco_requested(&mut self) -> bool;
    fn osc_lfxo_enabled(&mut self) -> bool;
    fn osc_lfxo_requested(&mut self) -> bool;
    fn set_dpll_m(&mut self, value: u64) -> ();
    fn set_dpll_n(&mut self, value: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Network.INetworkInterface`, member for member.
pub trait INetworkInterface: IAnalyzable {
}

/// C# `Antmicro.Renode.Peripherals.PCI.IPCIePeripheral`, member for member.
pub trait IPCIePeripheral: IPeripheral {
    fn configuration_read_double_word(&mut self, offset: i64) -> u32;
    fn configuration_write_double_word(&mut self, offset: i64, value: u32) -> ();
    fn memory_read_double_word(&mut self, bar: u32, offset: i64) -> u32;
    fn memory_write_double_word(&mut self, bar: u32, offset: i64, value: u32) -> ();
}

/// C# `Antmicro.Renode.Peripherals.SPI.ISFDPPeripheral`, member for member.
pub trait ISFDPPeripheral: IPeripheral {
    fn sfdp_signature(&mut self) -> Vec<u8>;
    fn set_sfdp_signature(&mut self, value: Vec<u8>) -> ();
}

/// C# `Antmicro.Renode.Peripherals.SPI.ISPIPeripheral`, member for member.
pub trait ISPIPeripheral: IPeripheral {
    fn finish_transmission(&mut self) -> ();
    fn transmit(&mut self, data: u8) -> u8;
}

/// C# `Antmicro.Renode.Peripherals.Sensor.ICPIPeripheral`, member for member.
pub trait ICPIPeripheral: II2CPeripheral {
    fn read_frame(&mut self) -> Vec<u8>;
}

/// C# `Antmicro.Renode.Peripherals.Sensor.IMagneticSensor`, member for member.
pub trait IMagneticSensor: ISensor {
    fn magnetic_flux_density_x(&mut self) -> i32;
    fn magnetic_flux_density_y(&mut self) -> i32;
    fn magnetic_flux_density_z(&mut self) -> i32;
    fn set_magnetic_flux_density_x(&mut self, value: i32) -> ();
    fn set_magnetic_flux_density_y(&mut self, value: i32) -> ();
    fn set_magnetic_flux_density_z(&mut self, value: i32) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Sensor.ISensor`, member for member.
pub trait ISensor: IPeripheral {
}

/// C# `Antmicro.Renode.Peripherals.Timers.IRiscVTimeProvider`, member for member.
pub trait IRiscVTimeProvider {
    fn timer_value(&mut self) -> u64;
}

/// C# `Antmicro.Renode.Peripherals.Timers.ITimer`, member for member.
pub trait ITimer: IHasFrequency {
    fn enabled(&mut self) -> bool;
    fn value(&mut self) -> u64;
    fn set_enabled(&mut self, value: bool) -> ();
    fn set_value(&mut self, value: u64) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Video.Allegro_E310.IFeedback`, member for member.
pub trait IFeedback {
}

/// C# `Antmicro.Renode.Peripherals.Wireless.IInterferenceQueueListener`, member for member.
pub trait IInterferenceQueueListener {
    fn inteference_queue_changed_callback(&mut self) -> ();
}

/// C# `Antmicro.Renode.Peripherals.Wireless.IRadio`, member for member.
pub trait IRadio: IPeripheral + INetworkInterface {
    fn subscribe_frame_sent(&mut self, handler: Option<Box<dyn FnMut(std::rc::Rc<std::cell::RefCell<dyn IRadio>>, Vec<u8>)>>);
    fn receive_frame(&mut self, frame: Vec<u8>, sender: std::rc::Rc<std::cell::RefCell<dyn IRadio>>) -> ();
    fn channel(&mut self) -> i32;
    fn set_channel(&mut self, value: i32) -> ();
}

/// C# `Antmicro.Renode.Storage.SCSI.Commands.IReadWrite10Command`, member for member.
pub trait IReadWrite10Command {
    fn logical_block_address(&mut self) -> u32;
    fn transfer_length(&mut self) -> u16;
    fn set_logical_block_address(&mut self, value: u32) -> ();
    fn set_transfer_length(&mut self, value: u16) -> ();
}

/// C# `Antmicro.Renode.Time.ITimeDomain`, member for member.
pub trait ITimeDomain {
}

/// C# `Antmicro.Renode.Utilities.Binding.INativeUnwindable`, member for member.
pub trait INativeUnwindable {
    fn native_unwind(&mut self) -> ();
}

/// C# `Antmicro.Renode.Utilities.GDB.IMultithreadCommand`, member for member.
pub trait IMultithreadCommand {
}

/// C# `Antmicro.Renode.Utilities.IAutoLoadType`, member for member.
pub trait IAutoLoadType {
}

/// C# `Antmicro.Renode.Utilities.IProgressMonitorHandler`, member for member.
pub trait IProgressMonitorHandler {
    fn finish(&mut self, id: i32) -> ();
    fn update(&mut self, id: i32, description: String, progress: Option<i32>) -> ();
}

/// C# `Antmicro.Renode.Utilities.RESD.IRESDSampleSource<T>`, member for member.
pub trait IRESDSampleSource<T>: IPeripheral {
    fn subscribe_new_sample(&mut self, handler: Option<Box<dyn FnMut(T)>>);
    fn sample(&mut self) -> T;
}

/// C# `Antmicro.Renode.Utilities.RESD.IUnderstandRESD`, member for member.
pub trait IUnderstandRESD: IPeripheral {
}
