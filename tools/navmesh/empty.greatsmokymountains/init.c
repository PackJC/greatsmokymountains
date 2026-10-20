// Empty mission for generating the navmesh (Bohemia's "Generating navigation mesh" page).
// No economy, no loot, no AI: the DayZ Diag server only has to load the terrain.
void main()
{

}

class CustomMission: MissionServer
{
	override PlayerBase CreateCharacter(PlayerIdentity identity, vector pos, ParamsReadContext ctx, string characterName)
	{
		Entity playerEnt;
		playerEnt = GetGame().CreatePlayer(identity, characterName, Vector(3645, 0, 14643), 0, "NONE");	// Gatlinburg
		Class.CastTo(m_player, playerEnt);

		GetGame().SelectPlayer(identity, m_player);

		return m_player;
	}

	override void StartingEquipSetup(PlayerBase player, bool clothesChosen)
	{
		player.RemoveAllItems();
	}
};

Mission CreateCustomMission(string path)
{
	return new CustomMission();
}
