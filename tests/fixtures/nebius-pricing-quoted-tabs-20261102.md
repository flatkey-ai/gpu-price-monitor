> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nebius.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Compute pricing in Nebius AI Cloud

This article provides detailed pricing for the Compute service in Nebius AI Cloud.

## How charges and prices work

Each group of chargeable items in this article has two time units associated with it:

* **Billing unit**: The minimum unit of usage for which you can be charged.
* **Pricing unit**: The unit of usage for which the prices are shown.

Charges for units smaller than the pricing unit are calculated proportionally.

> For example, for GPUs on running VMs, the **billing unit** is 1 second, and the **pricing unit** is 1 hour (3600 seconds). For 30 minutes of usage, you will be charged half the hourly price.

Prices in US dollars (USD, \$) apply to all customers except for companies from Israel, where prices in Israeli shekels (ILS, ₪) apply instead.

All prices are shown without any applicable taxes, including VAT. Due to rounding errors, usage costs shown in the web console and final charges may slightly differ from calculations based on the prices in this article.

## Prices

### Virtual machines (GPUs, vCPUs, RAM)

You are charged for computing resources (GPUs, vCPUs, RAM) of running virtual machines (VMs). Computing resources of stopped VMs are not charged (this does not apply to storage volumes; see [Volumes (disks and shared filesystems)](#volumes)).

* **Billing unit**: 1 second
* **Pricing unit**: 1 hour (3600 seconds)

> [!NOTE]
>
> Spot prices for preemptible GPU platforms are dynamic: they can increase or decrease based on available capacity, cluster utilization, customer demand and pricing preferences, and can change during use as often as every 15 minutes. The highest preemptible VM price is always one cent below the current pay-as-you-go (PAYG) on-demand rate for the same capacity. Current and historical spot prices are shown in the [web console](https://console.nebius.com).

#### NVIDIA® B300 NVLink, gpu-b300-sxm

The platform is only available in the `uk-south1`, `eu-west2` and `us-north1` [regions](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B300 NVLink | \$9.50 | 1 GPU hour |
> | Preemptible NVIDIA® B300 NVLink | [From \$0.99](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B300 NVLink | ₪29.45 | 1 GPU hour |
> | Preemptible NVIDIA® B300 NVLink | [From ₪3.069](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® B200 NVLink, gpu-b200-sxm

The platform is only available in the `us-central1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B200 NVLink | \$8.50 | 1 GPU hour |
> | Preemptible NVIDIA® B200 NVLink | [From \$0.99](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B200 NVLink | ₪26.35 | 1 GPU hour |
> | Preemptible NVIDIA® B200 NVLink | [From ₪3.069](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® B200 NVLink, gpu-b200-sxm-a

The platform is only available in the `me-west1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B200 NVLink | \$8.50 | 1 GPU hour |
> | Preemptible NVIDIA® B200 NVLink | [From \$0.99](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® B200 NVLink | ₪26.35 | 1 GPU hour |
> | Preemptible NVIDIA® B200 NVLink | [From ₪3.069](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® H200 NVLink

The platform is available in the `eu-north1`, `eu-north2`\*, `eu-west1` and `us-central1` [regions](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® H200 NVLink | \$5.40 | 1 GPU hour |
> | Preemptible NVIDIA® H200 NVLink | [From \$0.79](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® H200 NVLink | ₪16.74 | 1 GPU hour |
> | Preemptible NVIDIA® H200 NVLink | [From ₪2.449](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® H100 NVLink

The platform is only available in the `eu-north1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® H100 NVLink | \$4.50 | 1 GPU hour |
> | Preemptible NVIDIA® H100 NVLink | [From \$0.79](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® H100 NVLink | ₪13.95 | 1 GPU hour |
> | Preemptible NVIDIA® H100 NVLink | [From ₪2.449](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® RTX PRO™ 6000, gpu-rtx6000

The platform is only available in the `us-central1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® RTX PRO™ 6000 | \$1.80 | 1 GPU hour |
> | Preemptible NVIDIA® RTX PRO™ 6000 | [From \$0.79](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® RTX PRO™ 6000 | ₪5.58 | 1 GPU hour |
> | Preemptible NVIDIA® RTX PRO™ 6000 | [From ₪2.449](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® RTX PRO™ 6000, gpu-rtx6000-a

The platform is only available in the `uk-south2` and `eu-south1` [regions](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® RTX PRO™ 6000 | \$1.80 | 1 GPU hour |
> | Preemptible NVIDIA® RTX PRO™ 6000 | [From \$0.79](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® RTX PRO™ 6000 | ₪5.58 | 1 GPU hour |
> | Preemptible NVIDIA® RTX PRO™ 6000 | [From ₪2.449](https://docs.nebius.com/signup-billing/pricing-policy.md) | 1 GPU hour |

#### NVIDIA® L40S Intel

The platform is only available in the `eu-north1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® L40S Intel. GPU | \$1.35 | 1 GPU hour |
> | NVIDIA® L40S Intel. CPU | \$0.012 | 1 CPU hour |
> | NVIDIA® L40S Intel. RAM | \$0.0032 | 1 GiB hour |
> | Preemptible NVIDIA® L40S Intel. GPU | \$0.65 | 1 GPU hour |
> | Preemptible NVIDIA® L40S Intel. CPU | \$0.006 | 1 CPU hour |
> | Preemptible NVIDIA® L40S Intel. RAM | \$0.0016 | 1 GiB hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® L40S Intel. GPU | ₪4.185 | 1 GPU hour |
> | NVIDIA® L40S Intel. CPU | ₪0.0372 | 1 CPU hour |
> | NVIDIA® L40S Intel. RAM | ₪0.00992 | 1 GiB hour |
> | Preemptible NVIDIA® L40S Intel. GPU | ₪2.015 | 1 GPU hour |
> | Preemptible NVIDIA® L40S Intel. CPU | ₪0.0186 | 1 CPU hour |
> | Preemptible NVIDIA® L40S Intel. RAM | ₪0.00496 | 1 GiB hour |

#### NVIDIA® L40S AMD

The platform is only available for projects in the `eu-north1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® L40S AMD. GPU | \$1.35 | 1 GPU hour |
> | NVIDIA® L40S AMD. CPU | \$0.01 | 1 CPU hour |
> | NVIDIA® L40S AMD. RAM | \$0.0032 | 1 GiB hour |
> | Preemptible NVIDIA® L40S AMD. GPU | \$0.65 | 1 GPU hour |
> | Preemptible NVIDIA® L40S AMD. CPU | \$0.005 | 1 CPU hour |
> | Preemptible NVIDIA® L40S AMD. RAM | \$0.0016 | 1 GiB hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | NVIDIA® L40S AMD. GPU | ₪4.185 | 1 GPU hour |
> | NVIDIA® L40S AMD. CPU | ₪0.031 | 1 CPU hour |
> | NVIDIA® L40S AMD. RAM | ₪0.00992 | 1 GiB hour |
> | Preemptible NVIDIA® L40S AMD. GPU | ₪2.015 | 1 GPU hour |
> | Preemptible NVIDIA® L40S AMD. CPU | ₪0.0155 | 1 CPU hour |
> | Preemptible NVIDIA® L40S AMD. RAM | ₪0.00496 | 1 GiB hour |

#### Non-GPU AMD Epyc Genoa

The platform is available in all [regions](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | Non-GPU AMD Epyc Genoa. CPU | \$0.015 | 1 CPU hour |
> | Non-GPU AMD Epyc Genoa. RAM | \$0.0045 | 1 GiB hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | Non-GPU AMD Epyc Genoa. CPU | ₪0.0465 | 1 CPU hour |
> | Non-GPU AMD Epyc Genoa. RAM | ₪0.01395 | 1 GiB hour |

#### Non-GPU Intel Ice Lake

The platform is only available in the `eu-north1` [region](https://docs.nebius.com/overview/regions.md).

> [tab] USD
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | Non-GPU Intel Ice Lake. CPU | \$0.012 | 1 CPU hour |
> | Non-GPU Intel Ice Lake. RAM | \$0.0045 | 1 GiB hour |

> [tab] ILS
>
> | **Item** | **Price** | **Per** |
> | - | - | - |
> | Non-GPU Intel Ice Lake. CPU | ₪0.0372 | 1 CPU hour |
> | Non-GPU Intel Ice Lake. RAM | ₪0.01395 | 1 GiB hour |

### Volumes

You are charged for existing volumes (disks, disk snapshots and shared filesystems), regardless of whether they are added to VMs. Charges are based on volume sizes, regardless of how much space is taken up on a volume.

* **Billing unit**: 1 byte per 1 second
* **Pricing unit**: 1 GiB per 730 hours (2<sup>30</sup> bytes per 2,628,000 seconds \~ 1 month)

#### Disks

> [tab] USD
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Network SSD disk | \$0.071 |
> | Network SSD Non-replicated disk | \$0.053 |
> | Network SSD IO M3 disk | \$0.118 |

> [tab] ILS
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Network SSD disk | ₪0.221 |
> | Network SSD Non-replicated disk | ₪0.164 |
> | Network SSD IO M3 disk | ₪0.366 |

#### Disk snapshots

> [tab] USD
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Disk snapshot | \$0.071 |

> [tab] ILS
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Disk snapshot | ₪0.22 |

#### Shared filesystems

> [tab] USD
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Shared Filesystem SSD | \$0.08 |

> [tab] ILS
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Shared Filesystem SSD | ₪0.248 |

#### Local SSD disks

> [tab] USD
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Local SSD disk | \$0.065 |

> [tab] ILS
>
> | **Item** | **Price per 1 GiB per 730 hours** |
> | - | - |
> | Local SSD disk | ₪0.2015 |

Local SSD disks have finite write endurance defined by the manufacturer's Terabytes Written (TBW) rating. Workloads should not write more than the disk's total capacity per day. If a workload writes more data to a local SSD disk in a single day than the disk's total capacity, it exceeds the recommended write-endurance threshold.

If you expect your workload to exceed this threshold, [contact support](https://console.nebius.com/support/create-ticket) in advance to discuss capacity planning.
