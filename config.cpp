class CfgPatches
{
	class greatsmokymountains
	{
		units[]={};
		weapons[]={};
		requiredVersion=0.1;
		requiredAddons[]=
		{
			"DZ_Data",
			"DZ_Surfaces",
			"DZ_Surfaces_Bliss",
			"DZ_Worlds_Chernarusplus_World"
		};
		author="PackJC";
		name="Great Smoky Mountains";
		url="www.github.com/packjc";
		worlds[]=
		{
			"greatsmokymountains"
		};
	};
};
class CfgMissions
{
	class Cutscenes
	{
		class GreatSmokyMountainsIntro
		{
			directory="greatsmokymountains\data\scenes\intro.greatsmokymountains";
		};
	};
};
// The map's wildflower meadow (tools/paint_roads.py paints it on the open ground): Livonia's
// summer meadow grass under its own name (data\surfaces\gsm_meadow_*), so it gets its own
// clutter, about a third of it flowers.
class CfgSurfaces
{
	class en_grass1;
	class gsm_meadow: en_grass1
	{
		files="gsm_meadow*";
		character="gsm_meadow";
	};
};
class CfgSurfaceCharacters
{
	class gsm_meadow
	{
		probability[]={0.30000001,0.25,0.07,0.07,0.050000001,0.050000001,0.039999999,0.050000001,0.039999999,0.039999999,0.029999999,0.0099999998};
		names[]=
		{
			"Elytrigia_summer",
			"ElytrigiaGreen_summer",
			"ElytrigiaTall2_summer",
			"GrassBaseHypericum_summer",
			"GrassBaseCarduus_f_summer",
			"GrassFlowersWhiteShort_summer",
			"GrassFlowersWhite_summer",
			"GrassFlowersYellowShort_summer",
			"GrassFlowersYellow_summer",
			"GrassFlowersPurpleShort_summer",
			"GrassFlowersPurple_summer",
			"GrassFlowersPurpleTall_summer"
		};
	};
};
class cfgCharacterScenes
{
	class greatsmokymountains
	{
		class loc1
		{
			// Newfound Gap, looking at Mount Le Conte
			target[]={10114.8,7819.9,2009.6};
			position[]={11037.6,2998.5,1};
			fov=0.5236;
			date[]={1985,10,18,16,40};
			overcast=0.25;
			rain=0;
			fog=0.05;
		};
		class loc2
		{
			// Ben Morton Overlook, looking at view 1200 m out
			target[]={10095.6,3654.2,1389.4};
			position[]={11295.6,3654.2,1};
			fov=0.5236;
			date[]={1985,10,20,8,10};
			overcast=0.3;
			rain=0;
			fog=0.12;
		};
		class loc3
		{
			// Luftee Overlook, looking at view 700 m out
			target[]={10567.9,2192.2,1533.9};
			position[]={10031.7,2642.2,1};
			fov=0.5236;
			date[]={1985,6,14,18,20};
			overcast=0.15;
			rain=0;
			fog=0.02;
		};
		class loc4
		{
			// Chimney point, looking at Mount Mingus
			target[]={8003.5,3835.8,1752.4};
			position[]={6192.8,4798.8,1};
			fov=0.5236;
			date[]={1985,10,12,10,30};
			overcast=0.35;
			rain=0;
			fog=0.04;
		};
		class loc5
		{
			// Deep Creek Valley Overlook #1, looking at view 3000 m out
			target[]={8389.5,1560.8,1728.6};
			position[]={11389.5,1560.8,1};
			fov=0.5236;
			date[]={1985,10,25,15,10};
			overcast=0.4;
			rain=0;
			fog=0.06;
		};
		class loc6
		{
			// Charles A Webb Overlook, looking at view 1200 m out
			target[]={11671.1,56.0,1377.6};
			position[]={12798.8,466.4,1};
			fov=0.5236;
			date[]={1985,7,9,11,45};
			overcast=0.2;
			rain=0;
			fog=0.03;
		};
		class loc7
		{
			// Myrtle Point, looking at Mount Mingus
			target[]={8003.5,3835.8,1752.4};
			position[]={10533.0,7722.9,1};
			fov=0.5236;
			date[]={1985,9,28,7,5};
			overcast=0.1;
			rain=0;
			fog=0.1;
		};
		class loc8
		{
			// Cliff Top, looking at Mount Mingus
			target[]={8003.5,3835.8,1752.4};
			position[]={9474.4,7821.3,1};
			fov=0.5236;
			date[]={1985,10,5,17,50};
			overcast=0.2;
			rain=0;
			fog=0.04;
		};
		class loc9
		{
			// Gatlinburg, looking at view 2000 m out
			target[]={1903.0,13658.6,495.7};
			position[]={3635.0,14658.6,1};
			fov=0.5236;
			date[]={1985,10,22,9,15};
			overcast=0.45;
			rain=0;
			fog=0.05;
		};
		class loc10
		{
			// Sugarlands, looking at view 3000 m out
			target[]={1193.3,8126.7,1002.3};
			position[]={1193.3,11126.7,1};
			fov=0.5236;
			date[]={1985,4,26,13,0};
			overcast=0.5;
			rain=0;
			fog=0.03;
		};
		class loc11
		{
			// Twin Creeks, looking at view 700 m out
			target[]={4391.8,11088.0,785.7};
			position[]={4391.8,11788.0,1};
			fov=0.5236;
			date[]={1985,10,15,12,20};
			overcast=0.35;
			rain=0;
			fog=0.02;
		};
		class loc12
		{
			// Cartertown, looking at Cliff Top
			target[]={9438.5,7858.9,1987.4};
			position[]={6000.6,17143.1,1};
			fov=0.5236;
			date[]={1985,6,2,9,40};
			overcast=0.3;
			rain=0;
			fog=0.06;
		};
		class loc13
		{
			// Glade, looking at Balsam Point
			target[]={6858.0,7782.3,1766.0};
			position[]={8065.8,17379.3,1};
			fov=0.5236;
			date[]={1985,10,28,16,0};
			overcast=0.4;
			rain=0;
			fog=0.03;
		};
		class loc14
		{
			// Pinnacle, looking at West Point
			target[]={8632.7,7901.2,1919.9};
			position[]={12440.9,18207.8,1};
			fov=0.5236;
			date[]={1985,9,12,8,30};
			overcast=0.25;
			rain=0;
			fog=0.1;
		};
		class loc15
		{
			// Zion Grove, looking at view 700 m out
			target[]={9423.0,19412.0,534.5};
			position[]={9959.2,19862.0,1};
			fov=0.5236;
			date[]={1985,5,19,17,30};
			overcast=0.2;
			rain=0;
			fog=0.04;
		};
		class loc16
		{
			// Pittman Center, looking at view 700 m out
			target[]={13582.2,19742.3,469.0};
			position[]={14118.4,19292.3,1};
			fov=0.5236;
			date[]={1985,10,3,11,10};
			overcast=0.45;
			rain=0;
			fog=0.02;
		};
		class loc17
		{
			// Greenbrier Quarters & Ranger Station, looking at view 700 m out
			target[]={13266.5,16696.9,554.5};
			position[]={13144.9,16007.5,1};
			fov=0.5236;
			date[]={1985,4,12,14,30};
			overcast=0.5;
			rain=0;
			fog=0.05;
		};
	};
};
class CfgWorlds
{
	class DefaultLighting;
	class CAWorld;
	class ChernarusPlus: CAWorld
	{
		class Grid;
	};
	class greatsmokymountains: ChernarusPlus
	{
		access=3;
		worldId=2;
		cutscenes[]=
		{
			"GreatSmokyMountainsIntro"
		};
		description="Great Smoky Mountains";
		icon="";
		worldName="greatsmokymountains\greatsmokymountains.wrp";
		ceFiles="greatsmokymountains\ce";
		pictureMap="";
		pictureShot="";
		oceanMaterial="{11D1156E1D9DADF0}Graphics/Materials/water/oceanold_samplemap.emat";
		oceanNiceMaterial="{11D1156E1D9DADF0}Graphics/Materials/water/oceanold_samplemap.emat";
		oceanStormMaterial="{11D1156E1D9DADF0}Graphics/Materials/water/oceanold_samplemap.emat";
		hasOcean=0;
		volFogOffset=400;
		class Navmesh
		{
			navmeshName="\greatsmokymountains\navmesh\navmesh.nm";
			filterIsolatedIslandsOnLoad=1;
			visualiseOffset=0;
			class GenParams
			{
				tileWidth=50;
				cellSize1=0.25;
				cellSize2=0.1;
				cellSize3=0.1;
				filterIsolatedIslands=1;
				seedPosition[]={10564,0,10183};
				class Agent
				{
					diameter=0.60000002;
					standHeight=1.5;
					crouchHeight=1;
					proneHeight=0.5;
					maxStepHeight=0.44999999;
					maxSlope=60;
				};
				class Links
				{
					class ZedJump387_050
					{
						jumpLength=1.5;
						jumpHeight=0.5;
						minCenterHeight=0.30000001;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump0";
						flags[]=
						{
							"jumpOver"
						};
						color=1727987712;
					};
					class ZedJump388_050
					{
						jumpLength=1.5;
						jumpHeight=0.5;
						minCenterHeight=-0.5;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump0";
						flags[]=
						{
							"jumpOver"
						};
						color=1725781248;
					};
					class ZedJump387_110
					{
						jumpLength=3.9000001;
						jumpHeight=1.1;
						minCenterHeight=0.5;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump0";
						flags[]=
						{
							"jumpOver"
						};
						color=1711308800;
					};
					class ZedJump420_160
					{
						jumpLength=4;
						jumpHeight=1.6;
						minCenterHeight=1.1;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump0";
						flags[]=
						{
							"jumpOver"
						};
						color=1711276287;
					};
					class ZedJump265_210
					{
						jumpLength=2.45;
						jumpHeight=2.5;
						minCenterHeight=1.8;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump0";
						flags[]=
						{
							"climb"
						};
						color=1720975571;
					};
					class Fence50_110deer
					{
						typeId=100;
						jumpLength=8;
						jumpHeight=1.1;
						minCenterHeight=0.5;
						jumpDropdownMin=1;
						jumpDropdownMax=-1;
						areaType="jump2";
						flags[]=
						{
							"jumpOver"
						};
						color=1722460927;
					};
					class Fence110_160deer
					{
						typeId=101;
						jumpLength=8;
						jumpHeight=1.6;
						minCenterHeight=1.1;
						jumpDropdownMin=1;
						jumpDropdownMax=-1;
						areaType="jump3";
						flags[]=
						{
							"jumpOver"
						};
						color=1713700856;
					};
					class Fence50_110hen
					{
						typeId=110;
						jumpLength=4;
						jumpHeight=1.1;
						minCenterHeight=0.5;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump4";
						flags[]=
						{
							"jumpOver"
						};
						color=-22016;
					};
					class Fence110_160hen
					{
						typeId=111;
						jumpLength=4;
						jumpHeight=1.6;
						minCenterHeight=1.1;
						jumpDropdownMin=0.5;
						jumpDropdownMax=-0.5;
						areaType="jump4";
						flags[]=
						{
							"jumpOver"
						};
						color=-22016;
					};
				};
			};
		};
		plateFormat="ML$ - #####";
		plateLetters="ABCDEGHIKLMNOPRSTVXZ";
		longitude=-83.45;
		latitude=-35.65;
		mapDisplayNameKey="#STR_greatsmokymountains_map";
		mapDescriptionKey="#STR_greatsmokymountains_map_desc";
		mapTextureClosed="greatsmokymountains\data\map_folded_co.paa";
		mapTextureOpened="greatsmokymountains\data\map_unfolded_co.paa";
		mapTextureLegend="greatsmokymountains\data\map_legend_co.paa";
		userMapPath="greatsmokymountains\data\usermap";
		class AISpawnerParams
		{
		};
		class OutsideTerrain
		{
			satellite="greatsmokymountains\data\outside_sat_co.paa";
			enableTerrainSynth=1;
			class Layers
			{
				class Layer0
				{
					nopx="DZ\surfaces\data\terrain\cp_broadleaf_dense1_nopx.paa";
					texture="DZ\surfaces\data\terrain\cp_broadleaf_dense1_ca.paa";
				};
			};
		};
		class Grid: Grid
		{
			offsetX=0;
			offsetY=0;
			class Zoom1
			{
				zoomMax=0.15000001;
				format="XY";
				formatX="000";
				formatY="000";
				stepX=100;
				stepY=100;
			};
			class Zoom2
			{
				zoomMax=0.85000002;
				format="XY";
				formatX="00";
				formatY="00";
				stepX=1000;
				stepY=1000;
			};
			class Zoom3
			{
				zoomMax=1e+30;
				format="XY";
				formatX="0";
				formatY="0";
				stepX=10000;
				stepY=10000;
			};
		};
		startTime="8:30";
		startDate="01/05/1985";
		startWeather=0.1;
		startFog=0;
		forecastWeather=0.30000001;
		forecastFog=0;
		seagullPos[]={1272.842,150,14034.962};
		centerPosition[]={10240,10240,1331.0};
		ilsPosition[]={2545,3000};
		ilsDirection[]={0,0.079999998,1};
		ilsTaxiIn[]={2495,2725,2495,2850,2508,2860,2508,3000,2520,3010,2545,3000};
		ilsTaxiOff[]={2545,2445,2520,2425,2495,2445,2495,2725};
		drawTaxiway="false";
		class SecondaryAirports
		{
		};
		class ReplaceObjects
		{
		};
		class Animation
		{
			vehicles[]={};
		};
		class Lighting: DefaultLighting
		{
		};
		clutterGrid=1.11;
		clutterDist=55;
		noDetailDist=40;
		fullDetailDist=5;
		minTreesInForestSquare=3;
		minRocksInRockSquare=4;
		midDetailTexture="DZ\worlds\chernarusplus\data\middle_sat_mco.paa";
		terrainNormalTexture="greatsmokymountains\data\global_nohq.paa";
		class UsedTerrainMaterials
		{
			material0="DZ\surfaces\data\terrain\cp_broadleaf_dense1.rvmat";
			material1="DZ\surfaces\data\terrain\cp_broadleaf_dense2.rvmat";
			material2="DZ\surfaces\data\terrain\cp_broadleaf_sparse1.rvmat";
			material3="DZ\surfaces\data\terrain\cp_broadleaf_sparse2.rvmat";
			material4="DZ\surfaces\data\terrain\cp_concrete1.rvmat";
			material5="DZ\surfaces\data\terrain\cp_conifer_moss1.rvmat";
			material6="DZ\surfaces\data\terrain\cp_dirt.rvmat";
			material7="DZ\surfaces\data\terrain\cp_grass_tall.rvmat";
		};
		class Subdivision
		{
			class Fractal
			{
				rougness=5;
				maxRoad=0.02;
				maxTrack=0.5;
				maxSlopeFactor=0.050000001;
			};
			class WhiteNoise
			{
				rougness=2;
				maxRoad=0.0099999998;
				maxTrack=0.050000001;
				maxSlopeFactor=0.0024999999;
			};
			minY=0;
			minSlope=0.02;
		};
		class Names
		{
			class Settlement_Gatlinburg
			{
				name="Gatlinburg";
				position[]={3644.6,14643.4};
				type="Capital";
			};
			class Settlement_PittmanCenter
			{
				name="Pittman Center";
				position[]={14096.6,19377.6};
				type="City";
			};
			class Settlement_Cartertown
			{
				name="Cartertown";
				position[]={5996.6,17143.1};
				type="Village";
			};
			class Settlement_Glade
			{
				name="Glade";
				position[]={8064.8,17399.3};
				type="Village";
			};
			class Settlement_Pinnacle
			{
				name="Pinnacle";
				position[]={12433.5,18185.0};
				type="Village";
			};
			class Settlement_Sugarlands
			{
				name="Sugarlands";
				position[]={1157.8,11237.1};
				type="Village";
			};
			class Settlement_TwinCreeks
			{
				name="Twin Creeks";
				position[]={4383.3,11734.7};
				type="Village";
			};
			class Settlement_ZionGrove
			{
				name="Zion Grove";
				position[]={9936.0,19850.3};
				type="Village";
			};
			class Local_GreenbrierQuartersRangerStation
			{
				name="Greenbrier Quarters & Ranger Station";
				position[]={13096.1,16106.1};
				type="Local";
			};
			class Local_LeConteLodge
			{
				name="LeConte Lodge";
				position[]={9704.3,7890.3};
				type="Local";
			};
			class Local_LittleRiverRangerStation
			{
				name="Little River Ranger Station";
				position[]={1065.9,11897.8};
				type="Local";
			};
			class Local_NewfoundGap
			{
				name="Newfound Gap";
				position[]={11037.6,2998.5};
				type="Local";
			};
			class Camp_CabinFlats49
			{
				name="Cabin Flats #49";
				position[]={19828.7,3291.2};
				type="Camp";
			};
			class Camp_CampLeConteLuxuryOutdoorResort
			{
				name="Camp LeConte Luxury Outdoor Resort";
				position[]={9081.3,16486.9};
				type="Camp";
			};
			class Camp_EngineCreek32
			{
				name="Engine Creek #32";
				position[]={11782.4,13614.1};
				type="Camp";
			};
			class Camp_GatlinburgCreeksideRVResort
			{
				name="Gatlinburg Creekside RV Resort";
				position[]={8362.1,16032.2};
				type="Camp";
			};
			class Camp_GreenbrierCampground
			{
				name="Greenbrier Campground";
				position[]={12346.4,17591.9};
				type="Camp";
			};
			class Camp_IcewaterSpringShelter
			{
				name="Icewater Spring Shelter";
				position[]={14621.4,4996.2};
				type="Camp";
			};
			class Camp_KephartShelter
			{
				name="Kephart Shelter";
				position[]={16179.6,2775.5};
				type="Camp";
			};
			class Camp_Mile5321
			{
				name="Mile 53 #21";
				position[]={245.4,6152.9};
				type="Camp";
			};
			class Camp_MountCollinsShelter
			{
				name="Mount Collins Shelter";
				position[]={6847.2,1221.9};
				type="Camp";
			};
			class Camp_MountLeConteShelter
			{
				name="Mount LeConte Shelter";
				position[]={9928.6,7704.1};
				type="Camp";
			};
			class Camp_OutdoorResortsAtGatlinburg
			{
				name="Outdoor Resorts At Gatlinburg";
				position[]={19910.0,19630.1};
				type="Camp";
			};
			class Camp_PortersFlat31
			{
				name="Porters Flat #31";
				position[]={15131.6,8404.2};
				type="Camp";
			};
			class Camp_RoughCreek24
			{
				name="Rough Creek #24";
				position[]={1563.3,3789.8};
				type="Camp";
			};
			class Camp_SettlersCamp33
			{
				name="Settlers Camp #33";
				position[]={18736.6,18103.4};
				type="Camp";
			};
			class Camp_ThreeForks30
			{
				name="Three Forks #30";
				position[]={2902.3,1413.8};
				type="Camp";
			};
			class Camp_TwinCreekRVResort
			{
				name="Twin Creek RV Resort";
				position[]={6090.3,15799.1};
				type="Camp";
			};
			class Hill_AnakeestaKnob
			{
				name="Anakeesta Knob";
				position[]={12149.6,5527.9};
				type="Hill";
			};
			class Hill_BalsamPoint
			{
				name="Balsam Point";
				position[]={6858.0,7782.3};
				type="Hill";
			};
			class Hill_BriarKnob
			{
				name="Briar Knob";
				position[]={3910.9,15222.5};
				type="Hill";
			};
			class Hill_BrushyMountain
			{
				name="Brushy Mountain";
				position[]={10761.6,10439.9};
				type="Hill";
			};
			class Hill_BullHead
			{
				name="Bull Head";
				position[]={5524.6,8846.1};
				type="Hill";
			};
			class Hill_CharliesBunyon
			{
				name="Charlies Bunyon";
				position[]={15527.5,5826.0};
				type="Hill";
			};
			class Hill_ChimneyTops
			{
				name="Chimney Tops";
				position[]={6337.7,5164.6};
				type="Hill";
			};
			class Hill_CliffTop
			{
				name="Cliff Top";
				position[]={9438.5,7858.9};
				type="Hill";
			};
			class Hill_DevilsDen
			{
				name="Devils Den";
				position[]={17812.7,13984.1};
				type="Hill";
			};
			class Hill_HorseshoeMountain
			{
				name="Horseshoe Mountain";
				position[]={14549.1,6719.4};
				type="Hill";
			};
			class Hill_LaurelTop
			{
				name="Laurel Top";
				position[]={18819.5,8748.4};
				type="Hill";
			};
			class Hill_LittleGoshen
			{
				name="Little Goshen";
				position[]={476.0,2849.1};
				type="Hill";
			};
			class Hill_LookoutRock
			{
				name="Lookout Rock";
				position[]={10464.5,11585.2};
				type="Hill";
			};
			class Hill_MasaKnob
			{
				name="Masa Knob";
				position[]={15408.6,5511.4};
				type="Hill";
			};
			class Hill_MountAmbler
			{
				name="Mount Ambler";
				position[]={14001.7,4451.8};
				type="Hill";
			};
			class Hill_MountCollins
			{
				name="Mount Collins";
				position[]={6700.6,389.0};
				type="Hill";
			};
			class Hill_MountKephart
			{
				name="Mount Kephart";
				position[]={14324.2,5124.7};
				type="Hill";
			};
			class Hill_MountLeConte
			{
				name="Mount Le Conte";
				position[]={10114.8,7819.9};
				type="Hill";
			};
			class Hill_MountMingus
			{
				name="Mount Mingus";
				position[]={8003.5,3835.8};
				type="Hill";
			};
			class Hill_MountWeaver
			{
				name="Mount Weaver";
				position[]={9999.1,2418.0};
				type="Hill";
			};
			class Hill_MountWinnesoka
			{
				name="Mount Winnesoka";
				position[]={9762.6,11673.5};
				type="Hill";
			};
			class Hill_MyrtlePoint
			{
				name="Myrtle Point";
				position[]={10566.5,7701.0};
				type="Hill";
			};
			class Hill_PeregrinePeak
			{
				name="Peregrine Peak";
				position[]={9372.7,6267.8};
				type="Hill";
			};
			class Hill_PineyButt
			{
				name="Piney Butt";
				position[]={1457.5,15655.6};
				type="Hill";
			};
			class Hill_PineyMountain
			{
				name="Piney Mountain";
				position[]={7413.2,10646.3};
				type="Hill";
			};
			class Hill_PortersMountain
			{
				name="Porters Mountain";
				position[]={16507.4,7604.3};
				type="Hill";
			};
			class Hill_RichlandMountain
			{
				name="Richland Mountain";
				position[]={17567.0,2463.1};
				type="Hill";
			};
			class Hill_RoundTop
			{
				name="Round Top";
				position[]={9401.5,11981.3};
				type="Hill";
			};
			class Hill_SugarlandMountain
			{
				name="Sugarland Mountain";
				position[]={6588.2,1874.0};
				type="Hill";
			};
			class Hill_TheSawteeth
			{
				name="The Sawteeth";
				position[]={16832.8,6444.8};
				type="Hill";
			};
			class Hill_WestPoint
			{
				name="West Point";
				position[]={8632.7,7901.2};
				type="Hill";
			};
			class Hill_WoollyTopsMountain
			{
				name="Woolly Tops Mountain";
				position[]={18978.4,10132.9};
				type="Hill";
			};
			class ViewPoint_BenMortonOverlook
			{
				name="Ben Morton Overlook";
				position[]={11296.6,3660.1};
				type="ViewPoint";
			};
			class ViewPoint_CharlesAWebbOverlook
			{
				name="Charles A Webb Overlook";
				position[]={12769.8,452.8};
				type="ViewPoint";
			};
			class ViewPoint_ChimneyPoint
			{
				name="Chimney point";
				position[]={6296.7,4819.7};
				type="ViewPoint";
			};
			class ViewPoint_DeepCreekValleyOverlook1
			{
				name="Deep Creek Valley Overlook #1";
				position[]={11378.3,1546.7};
				type="ViewPoint";
			};
			class ViewPoint_DeepCreekValleyOverlook2
			{
				name="Deep Creek Valley Overlook #2";
				position[]={11787.2,1172.1};
				type="ViewPoint";
			};
			class ViewPoint_InspirationPoint
			{
				name="Inspiration Point";
				position[]={9562.0,5821.2};
				type="ViewPoint";
			};
			class ViewPoint_LufteeOverlook
			{
				name="Luftee Overlook";
				position[]={10042.6,2647.1};
				type="ViewPoint";
			};
			class Waterspring
			{
				name="";
				position[]={11993.4,1436.7};
				type="Waterspring";
			};
			class Waterspring_2
			{
				name="";
				position[]={9565.9,2950.0};
				type="Waterspring";
			};
			class Waterspring_3
			{
				name="";
				position[]={10340.3,13669.8};
				type="Waterspring";
			};
			class Waterspring_4
			{
				name="";
				position[]={6934.8,698.4};
				type="Waterspring";
			};
			class Waterspring_5
			{
				name="";
				position[]={1653.1,8920.4};
				type="Waterspring";
			};
			class Waterspring_6
			{
				name="";
				position[]={16510.2,18360.0};
				type="Waterspring";
			};
			class Waterspring_7
			{
				name="";
				position[]={612.7,13325.3};
				type="Waterspring";
			};
			class Waterspring_8
			{
				name="";
				position[]={268.4,7870.4};
				type="Waterspring";
			};
			class Waterspring_9
			{
				name="";
				position[]={7096.6,10304.9};
				type="Waterspring";
			};
			class Waterspring_10
			{
				name="";
				position[]={7670.5,12124.6};
				type="Waterspring";
			};
			class Waterspring_11
			{
				name="";
				position[]={1096.4,11537.6};
				type="Waterspring";
			};
			class Waterspring_12
			{
				name="";
				position[]={6615.1,12849.2};
				type="Waterspring";
			};
			class Waterspring_13
			{
				name="";
				position[]={14276.8,3953.8};
				type="Waterspring";
			};
			class Waterspring_14
			{
				name="";
				position[]={7853.7,8431.9};
				type="Waterspring";
			};
			class Waterspring_15
			{
				name="";
				position[]={1063.7,6994.8};
				type="Waterspring";
			};
			class Waterspring_16
			{
				name="";
				position[]={15486.1,15219.3};
				type="Waterspring";
			};
			class Waterspring_17
			{
				name="";
				position[]={7786.1,1271.3};
				type="Waterspring";
			};
			class Waterspring_18
			{
				name="";
				position[]={9534.7,14264.9};
				type="Waterspring";
			};
			class Waterspring_19
			{
				name="";
				position[]={20038.3,13405.2};
				type="Waterspring";
			};
			class Waterspring_20
			{
				name="";
				position[]={16346.6,16412.0};
				type="Waterspring";
			};
			class Waterspring_21
			{
				name="";
				position[]={9051.1,8404.7};
				type="Waterspring";
			};
			class Waterspring_22
			{
				name="";
				position[]={5302.1,10378.6};
				type="Waterspring";
			};
			class Waterspring_23
			{
				name="";
				position[]={16851.0,4610.2};
				type="Waterspring";
			};
			class Waterspring_24
			{
				name="";
				position[]={19187.6,17886.6};
				type="Waterspring";
			};
			class Waterspring_25
			{
				name="";
				position[]={645.1,300.6};
				type="Waterspring";
			};
			class Waterspring_26
			{
				name="";
				position[]={13172.7,3720.1};
				type="Waterspring";
			};
			class Waterspring_27
			{
				name="";
				position[]={11520.9,13911.3};
				type="Waterspring";
			};
			class Waterspring_28
			{
				name="";
				position[]={10945.6,1680.9};
				type="Waterspring";
			};
			class Waterspring_29
			{
				name="";
				position[]={1581.7,3791.9};
				type="Waterspring";
			};
			class Waterspring_30
			{
				name="";
				position[]={3433.6,9882.4};
				type="Waterspring";
			};
			class Waterspring_31
			{
				name="";
				position[]={19728.9,20332.1};
				type="Waterspring";
			};
			class Waterspring_32
			{
				name="";
				position[]={9433.6,13320.4};
				type="Waterspring";
			};
			class Waterspring_33
			{
				name="";
				position[]={2352.5,10231.7};
				type="Waterspring";
			};
			class Waterspring_34
			{
				name="";
				position[]={14493.1,4940.6};
				type="Waterspring";
			};
			class Waterspring_35
			{
				name="";
				position[]={10757.5,9542.7};
				type="Waterspring";
			};
			class Waterspring_36
			{
				name="";
				position[]={10833.7,2668.0};
				type="Waterspring";
			};
			class Waterspring_37
			{
				name="";
				position[]={1941.1,6040.0};
				type="Waterspring";
			};
			class Waterspring_38
			{
				name="";
				position[]={3815.3,12752.7};
				type="Waterspring";
			};
			class Waterspring_39
			{
				name="";
				position[]={10915.8,17533.5};
				type="Waterspring";
			};
			class Waterspring_40
			{
				name="";
				position[]={19079.4,8911.3};
				type="Waterspring";
			};
			class Waterspring_41
			{
				name="";
				position[]={3692.1,11295.2};
				type="Waterspring";
			};
			class Waterspring_42
			{
				name="";
				position[]={19731.0,18789.6};
				type="Waterspring";
			};
			class Waterspring_43
			{
				name="";
				position[]={2876.4,1180.3};
				type="Waterspring";
			};
			class Waterspring_44
			{
				name="";
				position[]={8719.4,12379.0};
				type="Waterspring";
			};
			class Waterspring_45
			{
				name="";
				position[]={18909.5,3346.9};
				type="Waterspring";
			};
			class Waterspring_46
			{
				name="";
				position[]={9144.8,5805.1};
				type="Waterspring";
			};
			class Waterspring_47
			{
				name="";
				position[]={2190.2,11265.4};
				type="Waterspring";
			};
			class Waterspring_48
			{
				name="";
				position[]={8550.5,10122.8};
				type="Waterspring";
			};
			class Waterspring_49
			{
				name="";
				position[]={1881.9,15765.3};
				type="Waterspring";
			};
			class Waterspring_50
			{
				name="";
				position[]={15833.9,19123.6};
				type="Waterspring";
			};
			class Waterspring_51
			{
				name="";
				position[]={137.9,1689.2};
				type="Waterspring";
			};
			class Waterspring_52
			{
				name="";
				position[]={7773.0,13091.2};
				type="Waterspring";
			};
			class Waterspring_53
			{
				name="";
				position[]={5607.5,17766.0};
				type="Waterspring";
			};
			class Waterspring_54
			{
				name="";
				position[]={7493.2,15339.5};
				type="Waterspring";
			};
			class Waterspring_55
			{
				name="";
				position[]={1296.5,1054.2};
				type="Waterspring";
			};
			class Waterspring_56
			{
				name="";
				position[]={326.1,10067.0};
				type="Waterspring";
			};
			class Waterspring_57
			{
				name="";
				position[]={20251.4,15834.7};
				type="Waterspring";
			};
			class Waterspring_58
			{
				name="";
				position[]={11094.2,12814.4};
				type="Waterspring";
			};
			class Waterspring_59
			{
				name="";
				position[]={5204.6,16731.1};
				type="Waterspring";
			};
			class Waterspring_60
			{
				name="";
				position[]={11330.9,18955.6};
				type="Waterspring";
			};
			class Waterspring_61
			{
				name="";
				position[]={1201.1,10613.9};
				type="Waterspring";
			};
			class Waterspring_62
			{
				name="";
				position[]={15073.0,20236.3};
				type="Waterspring";
			};
			class Waterspring_63
			{
				name="";
				position[]={11724.1,15729.4};
				type="Waterspring";
			};
			class Waterspring_64
			{
				name="";
				position[]={14035.8,13092.6};
				type="Waterspring";
			};
			class Waterspring_65
			{
				name="";
				position[]={14899.2,18210.3};
				type="Waterspring";
			};
			class Waterspring_66
			{
				name="";
				position[]={17247.6,15795.4};
				type="Waterspring";
			};
			class Waterspring_67
			{
				name="";
				position[]={17360.0,1877.2};
				type="Waterspring";
			};
			class Waterspring_68
			{
				name="";
				position[]={3632.8,16287.3};
				type="Waterspring";
			};
			class Waterspring_69
			{
				name="";
				position[]={12737.8,18424.6};
				type="Waterspring";
			};
			class Waterspring_70
			{
				name="";
				position[]={5381.2,15785.7};
				type="Waterspring";
			};
			class Waterpump
			{
				name="";
				position[]={13348.4,157.8};
				type="Waterpump";
			};
			class Waterpump_2
			{
				name="";
				position[]={16542.6,306.3};
				type="Waterpump";
			};
			class Waterpump_3
			{
				name="";
				position[]={7084.0,5824.8};
				type="Waterpump";
			};
			class Waterpump_4
			{
				name="";
				position[]={6405.1,10495.1};
				type="Waterpump";
			};
			class Waterpump_5
			{
				name="";
				position[]={7847.3,10769.5};
				type="Waterpump";
			};
			class Waterpump_6
			{
				name="";
				position[]={1334.0,11814.6};
				type="Waterpump";
			};
			class Waterpump_7
			{
				name="";
				position[]={15168.6,13650.8};
				type="Waterpump";
			};
			class Waterpump_8
			{
				name="";
				position[]={1644.3,12039.5};
				type="Waterpump";
			};
			class Waterpump_9
			{
				name="";
				position[]={5734.6,10294.5};
				type="Waterpump";
			};
			class Waterpump_10
			{
				name="";
				position[]={3879.4,12676.8};
				type="Waterpump";
			};
			class Waterpump_11
			{
				name="";
				position[]={15097.5,14099.6};
				type="Waterpump";
			};
			class Waterpump_12
			{
				name="";
				position[]={14815.0,13131.0};
				type="Waterpump";
			};
			class Waterpump_13
			{
				name="";
				position[]={5263.0,6018.1};
				type="Waterpump";
			};
			class Waterpump_14
			{
				name="";
				position[]={8710.3,5108.5};
				type="Waterpump";
			};
			class Waterpump_15
			{
				name="";
				position[]={1029.0,11797.8};
				type="Waterpump";
			};
			class Waterpump_16
			{
				name="";
				position[]={11076.3,2988.9};
				type="Waterpump";
			};
			class Waterpump_17
			{
				name="";
				position[]={2385.5,13779.1};
				type="Waterpump";
			};
			class Waterpump_18
			{
				name="";
				position[]={14640.3,12410.8};
				type="Waterpump";
			};
			class Waterpump_19
			{
				name="";
				position[]={15402.4,13633.2};
				type="Waterpump";
			};
			class Waterpump_20
			{
				name="";
				position[]={3511.6,13175.0};
				type="Waterpump";
			};
			class Waterpump_21
			{
				name="";
				position[]={6985.1,798.7};
				type="Waterpump";
			};
			class Waterpump_22
			{
				name="";
				position[]={2023.9,9035.2};
				type="Waterpump";
			};
			class Waterpump_23
			{
				name="";
				position[]={1056.3,11908.0};
				type="Waterpump";
			};
			class Waterpump_24
			{
				name="";
				position[]={13097.3,16115.1};
				type="Waterpump";
			};
			class Waterpump_25
			{
				name="";
				position[]={3221.0,13264.3};
				type="Waterpump";
			};
			class Waterpump_26
			{
				name="";
				position[]={12340.9,17594.3};
				type="Waterpump";
			};
			class Waterpump_27
			{
				name="";
				position[]={6679.7,6184.3};
				type="Waterpump";
			};
			class Waterpump_28
			{
				name="";
				position[]={7584.9,12391.3};
				type="Waterpump";
			};
			class Waterpump_29
			{
				name="";
				position[]={7254.6,12578.8};
				type="Waterpump";
			};
			class Waterpump_30
			{
				name="";
				position[]={3310.7,8354.9};
				type="Waterpump";
			};
			class Waterpump_31
			{
				name="";
				position[]={11098.8,3002.8};
				type="Waterpump";
			};
			class Waterpump_32
			{
				name="";
				position[]={3461.9,15951.7};
				type="Waterpump";
			};
			class Waterpump_33
			{
				name="";
				position[]={1945.0,12883.0};
				type="Waterpump";
			};
			class Waterpump_34
			{
				name="";
				position[]={7128.9,13262.2};
				type="Waterpump";
			};
			class Waterpump_35
			{
				name="";
				position[]={5400.4,11100.3};
				type="Waterpump";
			};
			class Waterpump_36
			{
				name="";
				position[]={3643.2,14637.3};
				type="Waterpump";
			};
			class Waterpump_37
			{
				name="";
				position[]={1661.1,12029.9};
				type="Waterpump";
			};
			class Waterpump_38
			{
				name="";
				position[]={9021.3,16199.1};
				type="Waterpump";
			};
			class Waterpump_39
			{
				name="";
				position[]={4367.6,11529.9};
				type="Waterpump";
			};
			class Fountain
			{
				name="";
				position[]={3155.7,14495.6};
				type="Fountain";
			};
			class Fountain_2
			{
				name="";
				position[]={3754.2,15693.0};
				type="Fountain";
			};
			class Fountain_3
			{
				name="";
				position[]={3694.4,15298.4};
				type="Fountain";
			};
			class Fountain_4
			{
				name="";
				position[]={3525.3,14531.0};
				type="Fountain";
			};
		};
	};
};
class CfgWorldList
{
	class greatsmokymountains
	{
	};
};
