> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nebius.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Types of virtual machines and GPUs in Nebius AI Cloud

Compute offers the following platforms for virtual machines (VMs) ([private regions](https://docs.nebius.com/overview/regions.md) are marked with `*`):

| Platform name | Platform ID | CPU | [Regions](https://docs.nebius.com/overview/regions.md) |
| - | - | - | - |
| NVIDIA® B300 NVLink with Intel Granite Rapids | gpu-b300-sxm | [Intel Xeon 6776P](https://www.intel.com/content/www/us/en/products/sku/243691/intel-xeon-6776p-processor-336m-cache-2-30-ghz/specifications.html) | `uk-south1`, `eu-west2`, `us-north1` |
| NVIDIA® B200 NVLink with Intel Emerald Rapids | gpu-b200-sxm | [Intel Xeon Platinum 8580](https://www.intel.com/content/www/us/en/products/sku/237250/intel-xeon-platinum-8580-processor-300m-cache-2-00-ghz/specifications.html) | `us-central1` |
| NVIDIA® B200 NVLink with Intel Emerald Rapids | gpu-b200-sxm-a | [Intel Xeon Platinum 8570](https://www.intel.com/content/www/us/en/products/sku/237264/intel-xeon-platinum-8570-processor-300m-cache-2-10-ghz/specifications.html) | `me-west1` |
| NVIDIA® RTX PRO™ 6000 with Intel Granite Rapids | gpu-rtx6000 | [Intel Xeon 6776P](https://www.intel.com/content/www/us/en/products/sku/243691/intel-xeon-6776p-processor-336m-cache-2-30-ghz/specifications.html) | `us-central1` |
| NVIDIA® RTX PRO™ 6000 with Intel Granite Rapids | gpu-rtx6000-a | [Intel Xeon 6776P](https://www.intel.com/content/www/us/en/products/sku/243691/intel-xeon-6776p-processor-336m-cache-2-30-ghz/specifications.html) | `uk-south2`, `eu-south1` |
| NVIDIA® H200 NVLink with Intel Sapphire Rapids | gpu-h200-sxm | [Intel Xeon Platinum 8468](https://ark.intel.com/content/www/us/en/ark/products/231735/intel-xeon-platinum-8468-processor-105m-cache-2-10-ghz.html) | `eu-north1`, `eu-north2`*\**, `eu-west1`, `us-central1` |
| NVIDIA® H100 NVLink with Intel Sapphire Rapids | gpu-h100-sxm | [Intel Xeon Platinum 8468](https://ark.intel.com/content/www/us/en/ark/products/231735/intel-xeon-platinum-8468-processor-105m-cache-2-10-ghz.html) | `eu-north1` |
| NVIDIA® L40S PCIe with Intel Ice Lake | gpu-l40s-a | [Intel Xeon Gold 6338](https://ark.intel.com/content/www/us/en/ark/products/212285/intel-xeon-gold-6338-processor-48m-cache-2-00-ghz.html) | `eu-north1` |
| NVIDIA® L40S PCIe with AMD EPYC Genoa | gpu-l40s-d | [AMD EPYC™ 9654](https://www.amd.com/en/products/processors/server/epyc/4th-generation-9004-and-8004-series/amd-epyc-9654.html) | `eu-north1` |
| Non-GPU AMD EPYC Genoa | cpu-d3 | [AMD EPYC™ 9654](https://www.amd.com/en/products/processors/server/epyc/4th-generation-9004-and-8004-series/amd-epyc-9654.html) | `eu-north1`, `eu-west1`, `me-west1`, `us-central1`, `uk-south1`, `uk-south2`, `eu-south1`, `eu-west2`, `us-north1`;  `eu-north2`*\** |
| Non-GPU Intel Ice Lake | cpu-e2 | [Intel Xeon Gold 6338](https://ark.intel.com/content/www/us/en/ark/products/212285/intel-xeon-gold-6338-processor-48m-cache-2-00-ghz.html) | `eu-north1` |

Each platform offers different *presets* for creating VMs. The presets vary by the number of GPUs (for platforms with GPUs), vCPUs and RAM size. The exact amount of these resources is indicated in the preset name. Thus, `1gpu-16vcpu-200gb` preset stands for a VM with 1 GPU, 16 vCPUs and 200 GiB (Nebius uses binary units. For example, a *gibibyte* (GiB) is 2<sup>30</sup> (1024<sup>3</sup>) bytes.) RAM.

Availability of platforms depends on a region and project. You can [get a list](https://docs.nebius.com/compute/virtual-machines/list-platforms.md) of platforms and presets supported in a given project. For VM platforms with GPUs, you can also use the [capacity advisor](https://docs.nebius.com/compute/virtual-machines/capacity-advisor.md) to get information about the availability of computing resources based on your quotas and the current physical capacity.

## GPU types

Compute provides VMs with the following GPU types:

| GPU | Architecture | Form factor | GPU memory | Memory bandwidth | InfiniBand interconnect | Network adapter | Platform | CPU |
| - | - | - | - | - | - | - | - | - |
| [NVIDIA B300](https://www.nvidia.com/en-us/data-center/dgx-b300/) | Blackwell Ultra | SXM | 288 GB HBM3e | 10 TB/s | 800 Gbps (8× ConnectX-8) | BlueField-3 400 Gbps | `gpu-b300-sxm` | [Intel Xeon 6776P](https://www.intel.com/content/www/us/en/products/sku/243691/intel-xeon-6776p-processor-336m-cache-2-30-ghz/specifications.html) |
| [NVIDIA B200](https://www.nvidia.com/en-us/data-center/dgx-b200/) | Blackwell | SXM | 180 GB HBM3e | 8 TB/s | 400 Gbps (8× ConnectX-7) | BlueField-3 400 Gbps | `gpu-b200-sxm`, `gpu-b200-sxm-a` | [Intel Xeon Platinum 8580](https://www.intel.com/content/www/us/en/products/sku/237250/intel-xeon-platinum-8580-processor-300m-cache-2-00-ghz/specifications.html), [Intel Xeon Platinum 8570](https://www.intel.com/content/www/us/en/products/sku/237264/intel-xeon-platinum-8570-processor-300m-cache-2-10-ghz/specifications.html) |
| [NVIDIA RTX PRO 6000 Server Edition](https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/) | Blackwell | PCIe Gen5 | 96 GB GDDR7 | 1.6 TB/s | — | BlueField-3 400 Gbps | `gpu-rtx6000`, `gpu-rtx6000-a` | [Intel Xeon 6776P](https://www.intel.com/content/www/us/en/products/sku/243691/intel-xeon-6776p-processor-336m-cache-2-30-ghz/specifications.html) |
| [NVIDIA H200](https://www.nvidia.com/en-us/data-center/h200/) | Hopper | SXM | 141 GB HBM3e | 4.8 TB/s | 400 Gbps (8× ConnectX-7) | BlueField-3 200 Gbps | `gpu-h200-sxm` | [Intel Xeon Platinum 8468](https://ark.intel.com/content/www/us/en/ark/products/231735/intel-xeon-platinum-8468-processor-105m-cache-2-10-ghz.html) |
| [NVIDIA H100](https://www.nvidia.com/en-us/data-center/h100/) | Hopper | SXM | 80 GB HBM3 | 3.35 TB/s | 400 Gbps (8× ConnectX-7) | ConnectX-6 100 Gbps | `gpu-h100-sxm` | [Intel Xeon Platinum 8468](https://ark.intel.com/content/www/us/en/ark/products/231735/intel-xeon-platinum-8468-processor-105m-cache-2-10-ghz.html) |
| [NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/) | Ada Lovelace | PCIe | 48 GB GDDR6 | 864 GB/s | — | — | `gpu-l40s-a`, `gpu-l40s-d` | [Intel Xeon Gold 6338](https://ark.intel.com/content/www/us/en/ark/products/212285/intel-xeon-gold-6338-processor-48m-cache-2-00-ghz.html), [AMD EPYC™ 9654](https://www.amd.com/en/products/processors/server/epyc/4th-generation-9004-and-8004-series/amd-epyc-9654.html) |

## Presets for GPU platforms

* NVIDIA® B300 NVLink with Intel Granite Rapids (`gpu-b300-sxm`), available in `uk-south1`, `eu-west2` and `us-north1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB (Nebius uses binary units. For example, a *gibibyte* (GiB) is 2<sup>30</sup> (1024<sup>3</sup>) bytes.) |
  | - | - | - | - |
  | `1gpu-24vcpu-346gb` | 1 | 24 | 346 |
  | `8gpu-192vcpu-2768gb` | 8 | 192 | 2768 |

* NVIDIA® B200 NVLink with Intel Emerald Rapids (`gpu-b200-sxm` and `gpu-b200-sxm-a`), available in `us-central1` and `me-west1` respectively:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB |
  | - | - | - | - |
  | `1gpu-20vcpu-224gb` | 1 | 20 | 224 |
  | `8gpu-160vcpu-1792gb` | 8 | 160 | 1792 |

* NVIDIA® H200 NVLink with Intel Sapphire Rapids (`gpu-h200-sxm`), available in `eu-north1`, `eu-north2`*\**, `eu-west1` and `us-central1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB | [Regions](https://docs.nebius.com/overview/regions.md) |
  | - | - | - | - | - |
  | `1gpu-16vcpu-200gb` | 1 | 16 | 200 | `eu-north1`, `eu-west1`, `us-central1`, `eu-north2` |
  | `8gpu-128vcpu-1600gb` | 8 | 128 | 1600 | `eu-north1`, `eu-west1`, `us-central1`, `eu-north2` |

* NVIDIA® H100 NVLink with Intel Sapphire Rapids (`gpu-h100-sxm`), available in `eu-north1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB |
  | - | - | - | - |
  | `1gpu-16vcpu-200gb` | 1 | 16 | 200 |
  | `8gpu-128vcpu-1600gb` | 8 | 128 | 1600 |

* NVIDIA® RTX PRO™ 6000 with Intel Granite Rapids, where `gpu-rtx6000` is available in `us-central1` and `gpu-rtx6000-a` is available in `uk-south2` and `eu-south1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB |
  | - | - | - | - |
  | `1gpu-24vcpu-218gb` | 1 | 24 | 218 |
  | `8gpu-192vcpu-1744gb` | 8 | 192 | 1744 |

* NVIDIA® L40S PCIe with Intel Ice Lake (`gpu-l40s-a`), available in `eu-north1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB |
  | - | - | - | - |
  | `1gpu-8vcpu-32gb` | 1 | 8 | 32 |
  | `1gpu-16vcpu-64gb` | 1 | 16 | 64 |
  | `1gpu-24vcpu-96gb` | 1 | 24 | 96 |
  | `1gpu-32vcpu-128gb` | 1 | 32 | 128 |
  | `1gpu-40vcpu-160gb` | 1 | 40 | 160 |

* NVIDIA® L40S PCIe with AMD EPYC Genoa (`gpu-l40s-d`), available in `eu-north1`:

  | Preset name | Number of GPUs | Number of vCPUs | RAM, GiB |
  | - | - | - | - |
  | `1gpu-16vcpu-96gb` | 1 | 16 | 96 |
  | `1gpu-32vcpu-192gb` | 1 | 32 | 192 |
  | `1gpu-48vcpu-288gb` | 1 | 48 | 288 |
  | `2gpu-64vcpu-384gb` | 2 | 64 | 384 |
  | `2gpu-96vcpu-576gb` | 2 | 96 | 576 |
  | `4gpu-128vcpu-768gb` | 4 | 128 | 768 |
  | `4gpu-192vcpu-1152gb` | 4 | 192 | 1152 |

### Presets compatible with GPU clusters

If you are adding a VM to a [GPU cluster](https://docs.nebius.com/compute/clusters/gpu/index.md), select from the following platforms and presets:

| Platform | Presets | [Regions](https://docs.nebius.com/overview/regions.md) |
| - | - | - |
| NVIDIA® B300 NVLink with Intel Granite Rapids  (`gpu-b300-sxm`) | `8gpu-192vcpu-2768gb` | `uk-south1`, `eu-west2`, `us-north1` |
| NVIDIA® B200 NVLink with Intel Emerald Rapids  (`gpu-b200-sxm`) | `8gpu-160vcpu-1792gb` | `us-central1` |
| NVIDIA® B200 NVLink with Intel Emerald Rapids  (`gpu-b200-sxm-a`) | `8gpu-160vcpu-1792gb` | `me-west1` |
| NVIDIA® H200 NVLink with Intel Sapphire Rapids  (`gpu-h200-sxm`) | `8gpu-128vcpu-1600gb` | `eu-north1`, `eu-north2`*\**, `eu-west1`, `us-central1` |
| NVIDIA® H100 NVLink with Intel Sapphire Rapids  (`gpu-h100-sxm`) | `8gpu-128vcpu-1600gb` | `eu-north1` |

Other presets and platforms are not compatible with GPU clusters.

## Presets for non-GPU platforms

* Non-GPU AMD EPYC Genoa (`cpu-d3`):

  | Preset name | Number of vCPUs | RAM, GiB | [Regions](https://docs.nebius.com/overview/regions.md) |
  | - | - | - | - |
  | `2vcpu-8gb` | 2 | 8 | All regions |
  | `4vcpu-16gb` | 4 | 16 | All regions |
  | `8vcpu-32gb` | 8 | 32 | All regions |
  | `16vcpu-64gb` | 16 | 64 | All regions |
  | `32vcpu-128gb` | 32 | 128 | All regions |
  | `48vcpu-192gb` | 48 | 192 | All regions |
  | `64vcpu-256gb` | 64 | 256 | All regions |
  | `96vcpu-384gb` | 96 | 384 | All regions |
  | `128vcpu-512gb` | 128 | 512 | All regions |
  | `160vcpu-640gb` | 160 | 640 | All regions except `eu-north1` and `eu-south1` |
  | `192vcpu-768gb` | 192 | 768 | All regions except `eu-north1` and `eu-south1` |
  | `224vcpu-896gb` | 224 | 896 | All regions except `eu-north1` and `eu-south1` |
  | `256vcpu-1024gb` | 256 | 1024 | All regions except `eu-north1` and `eu-south1` |

* Non-GPU Intel Ice Lake (`cpu-e2`), available in `eu-north1`:

  | Preset name | Number of vCPUs | RAM, GiB |
  | - | - | - |
  | `2vcpu-8gb` | 2 | 8 |
  | `4vcpu-16gb` | 4 | 16 |
  | `8vcpu-32gb` | 8 | 32 |
  | `16vcpu-64gb` | 16 | 64 |
  | `32vcpu-128gb` | 32 | 128 |
  | `48vcpu-192gb` | 48 | 192 |
  | `64vcpu-256gb` | 64 | 256 |
  | `80vcpu-320gb` | 80 | 320 |

## Compatibility with boot disk images

Nebius AI Cloud provides boot disk images for GPU and non-GPU VMs. The image that you choose for a VM must be compatible with the VM's platform. For compatibility details, see [Boot disk images for Compute virtual machines](https://docs.nebius.com/compute/storage/boot-disk-images.md).

## Compatibility with VM types

All platforms support regular VMs.

All platforms with GPUs also support [preemptible VMs](https://docs.nebius.com/compute/virtual-machines/preemptible.md).

To get an up-to-date list of platforms, run the `nebius compute platform list` [command](https://docs.nebius.com/cli/reference/compute/platform/list.md). The platforms available for preemptible VMs are marked as `allowed_for_preemptibles: true`.
