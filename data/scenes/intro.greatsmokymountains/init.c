// Main menu intro (CfgMissions >> Cutscenes >> GreatSmokyMountainsIntro), used when the
// main menu loads this world. The camera and character come from cfgCharacterScenes.
void main()
{
	Entity playerEnt = GetGame().CreatePlayer(NULL, "SurvivorM_Elias", "3645 0 14643", 0, "NONE");	// Gatlinburg
	PlayerBase player = (PlayerBase) playerEnt;
	GetGame().SelectPlayer(NULL, player);
}
