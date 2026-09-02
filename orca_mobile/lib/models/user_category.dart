class UserCategoryConfig {
  final String key;
  final String name;
  final String shortName;
  final String tagline;
  final String icon;
  final String vesselClass;
  final String vesselLabel;
  final String description;
  final List<String> focusBadges;

  const UserCategoryConfig({
    required this.key,
    required this.name,
    required this.shortName,
    required this.tagline,
    required this.icon,
    required this.vesselClass,
    required this.vesselLabel,
    required this.description,
    required this.focusBadges,
  });
}

class UserCategoryProfile {
  final String category;
  final String roleName;
  final String vesselClass;
  final String badgeEmoji;
  final String tagline;
  final int updatedAt;

  UserCategoryProfile({
    required this.category,
    required this.roleName,
    required this.vesselClass,
    required this.badgeEmoji,
    required this.tagline,
    required this.updatedAt,
  });

  Map<String, dynamic> toJson() => {
        'category': category,
        'roleName': roleName,
        'vesselClass': vesselClass,
        'badgeEmoji': badgeEmoji,
        'tagline': tagline,
        'updatedAt': updatedAt,
      };

  factory UserCategoryProfile.fromJson(Map<String, dynamic> j) =>
      UserCategoryProfile(
        category: j['category'] as String,
        roleName: j['roleName'] as String,
        vesselClass: j['vesselClass'] as String,
        badgeEmoji: j['badgeEmoji'] as String,
        tagline: j['tagline'] as String,
        updatedAt: j['updatedAt'] as int,
      );
}

const List<UserCategoryConfig> userCategories = [
  UserCategoryConfig(
    key: 'general_user',
    name: 'General User / Tourist',
    shortName: 'General Mariner',
    tagline: 'Coastal Weather & Beach Safety',
    icon: '🧭',
    vesselClass: 'small_fishing_boat',
    vesselLabel: 'General Maritime User',
    description: 'Coastal forecasts, beach safety, cyclone warnings for citizens.',
    focusBadges: ['Beach Safety', 'Tides', 'Cyclone Alerts'],
  ),
  UserCategoryConfig(
    key: 'fisherman',
    name: 'Traditional Fisherman',
    shortName: 'Fisherman',
    tagline: 'Artisanal & Nearshore Craft',
    icon: '🎣',
    vesselClass: 'small_fishing_boat',
    vesselLabel: 'Small Fishing Boat (< 2.5m)',
    description: 'PFZ, small craft safety, tides.',
    focusBadges: ['PFZ', 'Small Craft Safety', 'Tides'],
  ),
  UserCategoryConfig(
    key: 'trawler',
    name: 'Mechanized Trawler',
    shortName: 'Trawler',
    tagline: 'Deep-Sea Commercial Fishing',
    icon: '⛴️',
    vesselClass: 'mechanized_trawler',
    vesselLabel: 'Mechanized Trawler',
    description: 'Offshore PFZ, fleet crowding, bathymetry.',
    focusBadges: ['Fleet Crowding', 'Offshore PFZ', 'Bathymetry'],
  ),
  UserCategoryConfig(
    key: 'coastal_guard',
    name: 'Coast Guard & Police',
    shortName: 'Coast Guard',
    tagline: 'Border Patrol & SAR',
    icon: '🛡️',
    vesselClass: 'coastal_cargo',
    vesselLabel: 'Patrol Vessel',
    description: 'IMBL geofence, SAR drift, security.',
    focusBadges: ['IMBL Geofence', 'SAR', 'Security'],
  ),
  UserCategoryConfig(
    key: 'port_operator',
    name: 'Port & Commercial Vessel',
    shortName: 'Port Authority',
    tagline: 'Harbor & Cargo Logistics',
    icon: '🚢',
    vesselClass: 'coastal_cargo',
    vesselLabel: 'Commercial Cargo Vessel',
    description: 'Channel clearance, gale alerts, routing.',
    focusBadges: ['Channels', 'Gale Alerts', 'Bathymetry'],
  ),
  UserCategoryConfig(
    key: 'marine_scientist',
    name: 'Marine Researcher',
    shortName: 'Researcher',
    tagline: 'Oceanographic Analysis',
    icon: '🔬',
    vesselClass: 'small_fishing_boat',
    vesselLabel: 'Research Platform',
    description: 'SST/chlorophyll trends, satellite wind divergence.',
    focusBadges: ['SST Trends', 'Wind Divergence', 'Tides'],
  ),
];
